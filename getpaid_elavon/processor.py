import base64
import hashlib
import hmac
import logging
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from decimal import Decimal
from typing import ClassVar

from getpaid_core.enums import BackendMethod
from getpaid_core.enums import PaymentEvent
from getpaid_core.enums import PaymentStatus as InternalPaymentStatus
from getpaid_core.exceptions import InvalidCallbackError
from getpaid_core.processor import BaseProcessor
from getpaid_core.types import PaymentUpdate
from getpaid_core.types import TransactionResult

from getpaid_elavon.client import ElavonClient
from getpaid_elavon.types import PaymentStatus


class ElavonProcessor(BaseProcessor):
    slug: ClassVar[str] = "elavon"
    display_name: ClassVar[str] = "Elavon"
    accepted_currencies: ClassVar[list[str]] = []  # Elavon supports multiple currencies
    sandbox_url: ClassVar[str] = "https://uat.api.converge.eu.elavonaws.com"
    production_url: ClassVar[str] = "https://api.eu.convergepay.com"

    def _get_client(self) -> ElavonClient:
        return ElavonClient(
            merchant_alias_id=self.get_setting("merchant_alias_id"),
            secret_key=self.get_setting("secret_key"),
            sandbox=self.get_setting("sandbox", True),
        )

    def _get_logger(self) -> logging.Logger:
        """Get logger with configurable name from settings."""
        logger_name = self.get_setting("logger_name", "getpaid_elavon")
        return logging.getLogger(logger_name)

    def _build_paywall_context(self) -> dict:
        """Build Elavon order data from payment object.

        Converts payment data to Elavon API format.
        """
        raw_items = self.payment.order.get_items()
        items = [
            {
                "total": {
                    "amount": str(item.get("quantity", 1)),
                    "currencyCode": self.payment.currency,
                },
                "description": item.get("name", ""),
            }
            for item in raw_items
        ]

        return {
            "order_reference": str(self.payment.order.pk),
            "total_amount": str(self.payment.amount_required),
            "currency_code": self.payment.currency,
            "description": self.payment.description,
            "items": items,
            "custom_reference": self.payment.id,
        }

    async def prepare_transaction(self, **kwargs) -> TransactionResult:
        """Prepare an Elavon payment session.

        Creates order and payment session via Elavon API and returns redirect URL.
        """
        context = self._build_paywall_context()

        success_url = kwargs.get("success_url", "")
        cancel_url = kwargs.get("cancel_url", "")
        buyer_info = self.payment.order.get_buyer_info()

        async with self._get_client() as client:
            order_resp = await client.create_order(**context)
            elavon_order_url = order_resp.get("href")

            session_resp = await client.create_payment_session(
                elavon_order_url=elavon_order_url,
                return_url=success_url,
                cancel_url=cancel_url,
                custom_reference=self.payment.id,
                buyer_info=buyer_info,
            )

        payment_hpp_url = session_resp.get("url")

        return TransactionResult(
            redirect_url=payment_hpp_url,
            form_data=None,
            external_id=session_resp.get("id"),
            method=BackendMethod.GET,
            headers={},
        )

    async def verify_callback(self, data: dict, headers: dict, **kwargs) -> None:
        """Verify Elavon callback signature.

        Expects:
        - raw_body kwarg (preferred) or data["_raw_body"]
        - headers with Signature-{signer_id}

        Raises InvalidCallbackError if signature is missing or invalid.
        """
        raw_body = kwargs.get("raw_body")
        if raw_body is None:
            raw_body = data.get("_raw_body")
        if raw_body is None:
            raise InvalidCallbackError(
                "Missing raw_body in callback data. The framework adapter must pass the raw HTTP body."
            )
        if isinstance(raw_body, str):
            raw_body = raw_body.encode("utf-8")
        if not isinstance(raw_body, (bytes, bytearray)):
            raise InvalidCallbackError("raw_body must be bytes or str.")

        webhook_shared_secret = self.get_setting("webhook_shared_secret")
        webhook_signer_id = self.get_setting("webhook_signer_id")

        normalized_headers = {k.lower(): v for k, v in headers.items()}

        header_name = f"signature-{webhook_signer_id}"
        received_signature = normalized_headers.get(header_name)

        if not received_signature:
            raise InvalidCallbackError(f"Missing signature header: {header_name}")

        shared_secret_bytes = base64.b64decode(webhook_shared_secret)
        final_bytes = shared_secret_bytes + raw_body
        hash_result = hashlib.sha512(final_bytes).digest()

        expected_signature = base64.b64encode(hash_result).decode("utf-8")

        if not hmac.compare_digest(received_signature.strip(), expected_signature):
            self._get_logger().error(
                "Received bad signature for payment %s! Got '%s', expected '%s'",
                self.payment.id,
                received_signature,
                expected_signature,
            )
            raise InvalidCallbackError(f"BAD SIGNATURE: got '{received_signature}', expected '{expected_signature}'")

    async def handle_callback(self, data: dict, headers: dict, **kwargs) -> PaymentUpdate | None:
        """Handle Elavon webhook callback.

        Returns PaymentUpdate for FSM to process. Returns None for non-final events
        that don't change payment state (like RESET).
        Processes eventType from webhook:
        - saleAuthorized: Payment successful
        - saleDeclined: Payment failed
        - saleAuthorizationPending: Payment pending
        - reset: Payment reset for retry
        - expired: Payment session expired

        """
        event_type = data.get("eventType")
        provider_event_id = data.get("eventId")

        # Common provider data to include in all updates
        base_provider_data = {
            "event": data,
            "resource": data.get("resource"),
            "event_type": event_type,
        }

        match event_type:
            case PaymentStatus.SALE_AUTHORIZED:
                # For some payment methods, saleAuthorized is the first status
                self._get_logger().info(
                    "Payment authorized | payment_id: %s | amount: %s",
                    self.payment.id,
                    self.payment.amount_required,
                )
                return PaymentUpdate(
                    payment_event=PaymentEvent.PAYMENT_CAPTURED,
                    paid_amount=self.payment.amount_required,
                    external_id=data.get("resource", "").split("/")[-1],
                    provider_event_id=provider_event_id,
                    provider_data=base_provider_data,
                )

            case PaymentStatus.SALE_DECLINED:
                self._get_logger().warning(
                    "Payment declined | payment_id: %s",
                    self.payment.id,
                )
                return PaymentUpdate(
                    payment_event=PaymentEvent.FAILED,
                    provider_event_id=provider_event_id,
                    provider_data=base_provider_data,
                )

            case PaymentStatus.SALE_AUTHORIZATION_PENDING:
                self._get_logger().info(
                    "Payment authorization pending | payment_id: %s",
                    self.payment.id,
                )
                return PaymentUpdate(
                    payment_event=PaymentEvent.LOCKED,
                    locked_amount=self.payment.amount_required,
                    provider_event_id=provider_event_id,
                    provider_data=base_provider_data,
                )

            case PaymentStatus.RESET:
                # Reset is for retry, not a state change - just log
                self._get_logger().info(
                    "Payment reset for retry | payment_id: %s | session_id: %s",
                    self.payment.id,
                    self.payment.external_id,
                )
                return None  # No state change

            case PaymentStatus.EXPIRED:
                # Check if already locked (bank transfer scenario)
                if self.payment.status == InternalPaymentStatus.PRE_AUTH:
                    self._get_logger().info(
                        "Ignoring expired event for pre-authorized payment "
                        "(bank transfer may still be pending) | payment_id: %s",
                        self.payment.id,
                    )
                    return None  # No state change

                self._get_logger().warning(
                    "Payment session expired | payment_id: %s",
                    self.payment.id,
                )
                return PaymentUpdate(
                    payment_event=PaymentEvent.FAILED,
                    provider_event_id=provider_event_id,
                    provider_data=base_provider_data,
                )

            case _:
                self._get_logger().warning(
                    "Unknown event type: %s | payment_id: %s",
                    event_type,
                    self.payment.id,
                )
                return None

    async def fetch_payment_status(self, **kwargs) -> list[PaymentUpdate]:
        """PULL flow: poll Elavon notifications API for payment updates.

        Fetches all paymentSession notifications within a date range and
        converts them to PaymentUpdate objects. Each update carries
        ``external_id`` (the payment-session ID extracted from the resource
        URL) so the caller can match updates to local payment objects.

        The lookback window is controlled by the ``poll_window_hours`` setting
        (default 2). Override per-call via ``created_at_from`` / ``created_at_to``
        kwargs.

        Returns:
            List of PaymentUpdate objects sorted chronologically (oldest first).
        """
        poll_window_hours = self.get_setting("poll_window_hours", 2)
        now = datetime.now(tz=UTC)
        created_at_from = kwargs.get(
            "created_at_from",
            (now - timedelta(hours=poll_window_hours)).strftime("%Y-%m-%dT%H:%M"),
        )
        created_at_to = kwargs.get(
            "created_at_to",
            now.strftime("%Y-%m-%dT%H:%M"),
        )
        limit = kwargs.get("limit", 200)

        logger = self._get_logger()
        logger.info(
            "Polling notifications | from: %s | to: %s",
            created_at_from,
            created_at_to,
        )

        async with self._get_client() as client:
            notifications = await client.get_notifications(
                created_at_from=created_at_from,
                created_at_to=created_at_to,
                limit=limit,
            )

        session_notifications = [n for n in notifications if n.get("resourceType") == "paymentSession"]

        logger.info(
            "Fetched %d notifications (%d paymentSession)",
            len(notifications),
            len(session_notifications),
        )

        return self._build_updates_from_notifications(
            session_notifications,
            logger,
            payment_amount=getattr(self.payment, "amount_required", None),
        )

    @staticmethod
    def _extract_resource_id(resource_url: str) -> str:
        """Extract resource ID from Elavon resource URL."""
        return resource_url.rstrip("/").rsplit("/", 1)[-1]

    @staticmethod
    def _build_updates_from_notifications(
        notifications: list[dict],
        logger: logging.Logger,
        payment_amount: Decimal | None = None,
    ) -> list[PaymentUpdate]:
        """Convert raw Elavon notifications to PaymentUpdate list.

        Sorted chronologically (oldest first). Skips non-actionable events
        (reset, unknown). Each PaymentUpdate.external_id is the session ID
        extracted from the resource URL.
        """
        notifications.sort(key=lambda n: n.get("createdAt", ""))
        updates: list[PaymentUpdate] = []

        for notification in notifications:
            event_type = notification.get("eventType")
            notification_id = notification.get("id", "")
            session_id = ElavonProcessor._extract_resource_id(
                notification.get("resource", ""),
            )

            provider_data = {
                "notification_id": notification_id,
                "event_type": event_type,
                "resource": notification.get("resource", ""),
                "custom_reference": notification.get("customReference"),
            }

            match event_type:
                case PaymentStatus.SALE_AUTHORIZED:
                    logger.info(
                        "Payment authorized (poll) | session_id: %s",
                        session_id,
                    )
                    updates.append(
                        PaymentUpdate(
                            payment_event=PaymentEvent.PAYMENT_CAPTURED,
                            external_id=session_id,
                            provider_event_id=f"poll:{notification_id}",
                            provider_data=provider_data,
                        )
                    )

                case PaymentStatus.SALE_DECLINED:
                    logger.warning(
                        "Payment declined (poll) | session_id: %s",
                        session_id,
                    )
                    updates.append(
                        PaymentUpdate(
                            payment_event=PaymentEvent.FAILED,
                            external_id=session_id,
                            provider_event_id=f"poll:{notification_id}",
                            provider_data=provider_data,
                        )
                    )

                case PaymentStatus.SALE_AUTHORIZATION_PENDING:
                    logger.info(
                        "Payment authorization pending (poll) | session_id: %s",
                        session_id,
                    )
                    updates.append(
                        PaymentUpdate(
                            payment_event=PaymentEvent.LOCKED,
                            locked_amount=payment_amount,
                            external_id=session_id,
                            provider_event_id=f"poll:{notification_id}",
                            provider_data=provider_data,
                        )
                    )

                case PaymentStatus.EXPIRED:
                    logger.warning(
                        "Payment session expired (poll) | session_id: %s",
                        session_id,
                    )
                    updates.append(
                        PaymentUpdate(
                            payment_event=PaymentEvent.FAILED,
                            external_id=session_id,
                            provider_event_id=f"poll:{notification_id}",
                            provider_data=provider_data,
                        )
                    )

                case PaymentStatus.RESET:
                    logger.info(
                        "Payment reset (poll) | session_id: %s",
                        session_id,
                    )

                case _:
                    logger.warning(
                        "Unknown event type in poll: %s | session_id: %s",
                        event_type,
                        session_id,
                    )

        return updates

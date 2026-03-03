import base64
import contextlib
import hashlib
import hmac
import logging
from typing import ClassVar

from getpaid_core.exceptions import InvalidCallbackError
from getpaid_core.processor import BaseProcessor
from getpaid_core.types import TransactionResult
from transitions.core import MachineError

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

    def _build_paywall_context(self, **kwargs) -> dict:
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
        self.config = kwargs.get("config")
        client = self._get_client()
        context = self._build_paywall_context(**kwargs)

        # Create order
        order_resp = await client.create_order(**context)
        elavon_order_url = order_resp.get("href")

        # Get URLs from kwargs or settings
        success_url = kwargs.get("success_url", "")
        cancel_url = kwargs.get("cancel_url", "")

        # Get buyer info
        buyer_info = self.payment.order.get_buyer_info()

        # Create payment session
        session_resp = await client.create_payment_session(
            elavon_order_url=elavon_order_url,
            return_url=success_url,
            cancel_url=cancel_url,
            custom_reference=self.payment.id,
            buyer_info=buyer_info,
        )

        self.payment.external_id = session_resp.get("id")

        payment_hpp_url = session_resp.get("url")

        return TransactionResult(
            redirect_url=payment_hpp_url,
            form_data=None,
            method="POST",
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

        header_name = f"Signature-{webhook_signer_id}"
        received_signature = headers.get(header_name)

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

    async def handle_callback(self, data: dict, headers: dict, **kwargs) -> None:
        """Handle Elavon webhook callback.

        Uses payment.may_trigger() to check if transitions are
        valid before firing them. FSM must be attached to
        self.payment before this method is called.

        Processes eventType from webhook:
        - saleAuthorized: Payment successful
        - saleAuthorizationPending: Payment pending
        - expired: Payment session expired=failed
        """
        event_type = data.get("eventType")

        if event_type == PaymentStatus.SALE_AUTHORIZED:
            # For some payment methods, saleAuthorized is the first status
            if self.payment.may_trigger("confirm_lock"):  # type: ignore[union-attr]
                self.payment.confirm_lock()  # type: ignore[union-attr]

            if self.payment.may_trigger("confirm_payment"):  # type: ignore[union-attr]
                self.payment.confirm_payment()  # type: ignore[union-attr]
                with contextlib.suppress(MachineError):
                    self.payment.mark_as_paid()  # type: ignore[union-attr]

                self._get_logger().info(
                    "Payment authorized successfully | payment_id: %s | amount: %s",
                    self.payment.id,
                    str(self.payment.amount_required),
                )
            else:
                self._get_logger().debug(
                    "Cannot confirm payment",
                    extra={
                        "payment_id": self.payment.id,
                        "payment_status": self.payment.status,
                    },
                )

        elif event_type == PaymentStatus.SALE_AUTHORIZATION_PENDING:
            if self.payment.may_trigger("confirm_lock"):  # type: ignore[union-attr]
                self.payment.confirm_lock()  # type: ignore[union-attr]
                self._get_logger().info(
                    "Payment authorization pending | payment_id: %s",
                    self.payment.id,
                )
            else:
                self._get_logger().debug(
                    "Already locked",
                    extra={
                        "payment_id": self.payment.id,
                        "payment_status": self.payment.status,
                    },
                )

        elif event_type == PaymentStatus.EXPIRED:
            if self.payment.may_trigger("fail"):  # type: ignore[union-attr]
                self.payment.fail()  # type: ignore[union-attr]
                self._get_logger().warning(
                    "Payment session expired | payment_id: %s",
                    self.payment.id,
                )

        else:
            self._get_logger().warning(
                "Unknown event type received: %s | payment_id: %s",
                event_type,
                self.payment.id,
            )

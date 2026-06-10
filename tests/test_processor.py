import base64
import hashlib
import json

import httpx
import pytest
from getpaid_core.enums import PaymentStatus
from getpaid_core.fsm import apply_payment_update

from getpaid_elavon.processor import ElavonProcessor
from getpaid_elavon.types import PaymentStatus as ElavonPaymentStatus

from .conftest import ELAVON_CONFIG
from .conftest import FAKE_BASE_URL
from .conftest import FakePayment
from .conftest import make_mock_payment


NOTIFICATIONS_URL = f"{FAKE_BASE_URL}/notifications"


def _make_processor(payment=None, config=None):
    if payment is None:
        payment = make_mock_payment()
    if config is None:
        config = ELAVON_CONFIG.copy()
    processor = ElavonProcessor(payment=payment, config=config)
    return processor


def _sign_webhook(data: dict, shared_secret: str, signer_id: str) -> str:
    json_body = json.dumps(data, separators=(",", ":"))
    raw_body = json_body.encode("utf-8")
    shared_secret_bytes = base64.b64decode(shared_secret)
    final_bytes = shared_secret_bytes + raw_body
    hash_result = hashlib.sha512(final_bytes).digest()
    return base64.b64encode(hash_result).decode("utf-8")


def _webhook_data(event_type: str = "saleAuthorized") -> dict:
    return {
        "href": f"{FAKE_BASE_URL}/notifications/notif-123",
        "id": "notif-123",
        "merchant": f"{FAKE_BASE_URL}/merchants/merchant-123",
        "createdAt": "2026-03-06T10:00:00.000Z",
        "eventType": event_type,
        "resourceType": "paymentSession",
        "resource": f"{FAKE_BASE_URL}/payment-sessions/session-123",
        "customReference": "payment-uuid-123",
    }


class TestPrepareTransaction:
    async def test_prepare_transaction_success(self, respx_mock):
        order_response = {
            "href": f"{FAKE_BASE_URL}/orders/order-123",
            "id": "order-123",
        }
        respx_mock.post(f"{FAKE_BASE_URL}/orders").respond(
            json=order_response,
            status_code=201,
        )

        session_response = {
            "href": f"{FAKE_BASE_URL}/payment-sessions/session-123",
            "id": "session-123",
            "url": "https://hpp.elavon.com/pay/session-123",
        }
        respx_mock.post(f"{FAKE_BASE_URL}/payment-sessions").respond(
            json=session_response,
            status_code=201,
        )

        processor = _make_processor()
        result = await processor.prepare_transaction(
            success_url="https://shop.example.com/success",
            cancel_url="https://shop.example.com/cancel",
            config=ELAVON_CONFIG.copy(),
        )

        assert result.redirect_url == "https://hpp.elavon.com/pay/session-123"
        assert result.external_id == "session-123"
        assert result.form_data is None


class TestVerifyCallback:
    async def test_valid_signature(self):
        data = _webhook_data()
        json_body = json.dumps(data, separators=(",", ":"))
        raw_body = json_body.encode("utf-8")

        signature = _sign_webhook(
            data,
            ELAVON_CONFIG["webhook_shared_secret"],
            ELAVON_CONFIG["webhook_signer_id"],
        )

        headers = {
            f"Signature-{ELAVON_CONFIG['webhook_signer_id']}": signature,
        }

        processor = _make_processor()
        await processor.verify_callback(data=data, headers=headers, raw_body=raw_body)

    async def test_missing_signature_raises(self):
        data = _webhook_data()
        json_body = json.dumps(data, separators=(",", ":"))
        raw_body = json_body.encode("utf-8")

        headers = {}

        processor = _make_processor()
        with pytest.raises(Exception, match="Missing signature header"):
            await processor.verify_callback(data=data, headers=headers, raw_body=raw_body)

    async def test_bad_signature_raises(self):
        data = _webhook_data()
        json_body = json.dumps(data, separators=(",", ":"))
        raw_body = json_body.encode("utf-8")

        headers = {
            f"Signature-{ELAVON_CONFIG['webhook_signer_id']}": "bad_signature",
        }

        processor = _make_processor()
        with pytest.raises(Exception, match="BAD SIGNATURE"):
            await processor.verify_callback(data=data, headers=headers, raw_body=raw_body)

    async def test_missing_raw_body_raises(self):
        data = _webhook_data()
        headers = {}

        processor = _make_processor()
        with pytest.raises(Exception, match="Missing raw_body"):
            await processor.verify_callback(data=data, headers=headers)


class TestHandleCallback:
    async def test_sale_authorized_marks_paid(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.SALE_AUTHORIZED)
        update = await processor.handle_callback(data=data, headers={})
        apply_payment_update(payment, update)

        assert payment.status == PaymentStatus.PAID

    async def test_sale_authorization_pending_locks_payment(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.SALE_AUTHORIZATION_PENDING)
        update = await processor.handle_callback(data=data, headers={})
        apply_payment_update(payment, update)

        assert payment.status == PaymentStatus.PRE_AUTH

    async def test_expired_fails_payment(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.EXPIRED)
        update = await processor.handle_callback(data=data, headers={})
        apply_payment_update(payment, update)

        assert payment.status == PaymentStatus.FAILED

    async def test_expired_preserves_pre_auth_payment(self):
        payment = FakePayment(status=PaymentStatus.PRE_AUTH)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.EXPIRED)
        update = await processor.handle_callback(data=data, headers={})
        apply_payment_update(payment, update)

        assert payment.status == PaymentStatus.PRE_AUTH

    async def test_reset_does_not_change_status(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.RESET)
        update = await processor.handle_callback(data=data, headers={})
        apply_payment_update(payment, update)

        assert payment.status == PaymentStatus.NEW

    async def test_unknown_event_type_does_not_change_status(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type="unknownEventType")
        update = await processor.handle_callback(data=data, headers={})
        apply_payment_update(payment, update)

        assert payment.status == PaymentStatus.NEW


def _notification(
    event_type: str,
    resource_type: str = "paymentSession",
    session_id: str = "session-abc",
    notification_id: str = "notif-1",
    created_at: str = "2026-02-26T14:26:44.000Z",
    custom_reference: str | None = None,
) -> dict:
    resource_base = "payment-sessions" if resource_type == "paymentSession" else "transactions"
    return {
        "href": f"{FAKE_BASE_URL}/notifications/{notification_id}",
        "id": notification_id,
        "merchant": f"{FAKE_BASE_URL}/merchants/merchant-123",
        "createdAt": created_at,
        "eventType": event_type,
        "resourceType": resource_type,
        "resource": f"{FAKE_BASE_URL}/{resource_base}/{session_id}",
        "customReference": custom_reference,
    }


def _notifications_response(
    items: list[dict],
    next_url: str | None = None,
) -> dict:
    return {
        "href": NOTIFICATIONS_URL,
        "first": NOTIFICATIONS_URL,
        "next": next_url,
        "pageToken": None,
        "nextPageToken": None,
        "limit": 200,
        "size": len(items),
        "items": items,
    }


class TestFetchPaymentStatus:
    async def test_returns_list_of_updates(self, respx_mock):
        items = [
            _notification(
                event_type="saleAuthorized",
                session_id="sess-1",
                notification_id="n1",
            ),
        ]
        respx_mock.get(url__startswith=NOTIFICATIONS_URL).respond(
            json=_notifications_response(items),
        )

        processor = _make_processor()
        updates = await processor.fetch_payment_status(
            created_at_from="2026-02-26T14:00",
            created_at_to="2026-02-26T15:00",
        )

        assert len(updates) == 1
        assert updates[0].external_id == "sess-1"
        assert updates[0].payment_event.value == "payment_captured"

    async def test_filters_only_payment_session_resources(self, respx_mock):
        items = [
            _notification(
                event_type="saleAuthorized",
                resource_type="paymentSession",
                session_id="sess-1",
                notification_id="n1",
            ),
            _notification(
                event_type="saleAuthorized",
                resource_type="transaction",
                session_id="txn-1",
                notification_id="n2",
            ),
        ]
        respx_mock.get(url__startswith=NOTIFICATIONS_URL).respond(
            json=_notifications_response(items),
        )

        processor = _make_processor()
        updates = await processor.fetch_payment_status(
            created_at_from="2026-02-26T14:00",
            created_at_to="2026-02-26T15:00",
        )

        assert len(updates) == 1
        assert updates[0].external_id == "sess-1"

    async def test_handles_pagination(self, respx_mock):
        page1_items = [
            _notification(
                event_type="saleAuthorizationPending",
                session_id="sess-1",
                notification_id="n1",
                created_at="2026-02-26T14:26:38.000Z",
            ),
        ]
        page2_items = [
            _notification(
                event_type="saleAuthorized",
                session_id="sess-1",
                notification_id="n2",
                created_at="2026-02-26T14:26:44.000Z",
            ),
        ]
        page2_url = f"{NOTIFICATIONS_URL}?page=2"

        respx_mock.get(url__startswith=NOTIFICATIONS_URL).mock(
            side_effect=[
                httpx.Response(
                    200,
                    json=_notifications_response(page1_items, next_url=page2_url),
                ),
                httpx.Response(
                    200,
                    json=_notifications_response(page2_items),
                ),
            ],
        )

        processor = _make_processor()
        updates = await processor.fetch_payment_status(
            created_at_from="2026-02-26T14:00",
            created_at_to="2026-02-26T15:00",
        )

        assert len(updates) == 2
        assert updates[0].provider_event_id == "poll:n1"
        assert updates[1].provider_event_id == "poll:n2"

    async def test_empty_response_returns_empty_list(self, respx_mock):
        respx_mock.get(url__startswith=NOTIFICATIONS_URL).respond(
            json=_notifications_response([]),
        )

        processor = _make_processor()
        updates = await processor.fetch_payment_status(
            created_at_from="2026-02-26T14:00",
            created_at_to="2026-02-26T15:00",
        )

        assert updates == []

    async def test_maps_all_event_types(self, respx_mock):
        items = [
            _notification(
                event_type="saleAuthorized",
                session_id="s1",
                notification_id="n1",
                created_at="2026-02-26T14:26:01.000Z",
            ),
            _notification(
                event_type="saleDeclined",
                session_id="s2",
                notification_id="n2",
                created_at="2026-02-26T14:26:02.000Z",
            ),
            _notification(
                event_type="saleAuthorizationPending",
                session_id="s3",
                notification_id="n3",
                created_at="2026-02-26T14:26:03.000Z",
            ),
            _notification(
                event_type="expired",
                session_id="s4",
                notification_id="n4",
                created_at="2026-02-26T14:26:04.000Z",
            ),
            _notification(
                event_type="reset",
                session_id="s5",
                notification_id="n5",
                created_at="2026-02-26T14:26:05.000Z",
            ),
        ]
        respx_mock.get(url__startswith=NOTIFICATIONS_URL).respond(
            json=_notifications_response(items),
        )

        processor = _make_processor()
        updates = await processor.fetch_payment_status(
            created_at_from="2026-02-26T14:00",
            created_at_to="2026-02-26T15:00",
        )

        # reset is skipped, 4 actionable events
        assert len(updates) == 4
        events = [u.payment_event.value for u in updates]
        assert events == [
            "payment_captured",
            "failed",
            "locked",
            "failed",
        ]

    async def test_preserves_custom_reference_in_provider_data(self, respx_mock):
        items = [
            _notification(
                event_type="saleAuthorized",
                session_id="sess-1",
                notification_id="n1",
                custom_reference="payment-uuid-abc",
            ),
        ]
        respx_mock.get(url__startswith=NOTIFICATIONS_URL).respond(
            json=_notifications_response(items),
        )

        processor = _make_processor()
        updates = await processor.fetch_payment_status(
            created_at_from="2026-02-26T14:00",
            created_at_to="2026-02-26T15:00",
        )

        assert updates[0].provider_data["custom_reference"] == "payment-uuid-abc"

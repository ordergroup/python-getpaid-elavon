import base64
import hashlib
import json

import pytest
from getpaid_core.enums import PaymentStatus
from getpaid_core.fsm import create_payment_machine

from getpaid_elavon.processor import ElavonProcessor
from getpaid_elavon.types import PaymentStatus as ElavonPaymentStatus

from .conftest import ELAVON_CONFIG
from .conftest import FakePayment
from .conftest import make_mock_payment


SANDBOX_URL = "https://uat.api.test.eu.elavonaws.com"


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
        "href": f"{SANDBOX_URL}/notifications/notif-123",
        "id": "notif-123",
        "merchant": f"{SANDBOX_URL}/merchants/merchant-123",
        "createdAt": "2026-03-06T10:00:00.000Z",
        "eventType": event_type,
        "resourceType": "paymentSession",
        "resource": f"{SANDBOX_URL}/payment-sessions/session-123",
        "customReference": "payment-uuid-123",
    }


class TestPrepareTransaction:
    async def test_prepare_transaction_success(self, respx_mock):
        order_response = {
            "href": f"{SANDBOX_URL}/orders/order-123",
            "id": "order-123",
        }
        respx_mock.post(f"{SANDBOX_URL}/orders").respond(
            json=order_response,
            status_code=201,
        )

        session_response = {
            "href": f"{SANDBOX_URL}/payment-sessions/session-123",
            "id": "session-123",
            "url": "https://hpp.elavon.com/pay/session-123",
        }
        respx_mock.post(f"{SANDBOX_URL}/payment-sessions").respond(
            json=session_response,
            status_code=201,
        )

        processor = _make_processor()
        result = await processor.prepare_transaction(
            success_url="https://shop.example.com/success",
            cancel_url="https://shop.example.com/cancel",
            config=ELAVON_CONFIG.copy(),
        )

        assert result["redirect_url"] == "https://hpp.elavon.com/pay/session-123"
        assert result["method"] == "POST"
        assert result["form_data"] is None
        assert processor.payment.external_id == "session-123"


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
        create_payment_machine(payment)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.SALE_AUTHORIZED)
        await processor.handle_callback(data=data, headers={})

        assert payment.status == PaymentStatus.PAID

    async def test_sale_authorization_pending_locks_payment(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        create_payment_machine(payment)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.SALE_AUTHORIZATION_PENDING)
        await processor.handle_callback(data=data, headers={})

        assert payment.status == PaymentStatus.PRE_AUTH

    async def test_expired_fails_payment(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        create_payment_machine(payment)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.EXPIRED)
        await processor.handle_callback(data=data, headers={})

        assert payment.status == PaymentStatus.FAILED

    async def test_expired_preserves_pre_auth_payment(self):
        payment = FakePayment(status=PaymentStatus.PRE_AUTH)
        create_payment_machine(payment)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.EXPIRED)
        await processor.handle_callback(data=data, headers={})

        assert payment.status == PaymentStatus.PRE_AUTH

    async def test_reset_does_not_change_status(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        create_payment_machine(payment)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type=ElavonPaymentStatus.RESET)
        await processor.handle_callback(data=data, headers={})

        assert payment.status == PaymentStatus.NEW

    async def test_unknown_event_type_does_not_change_status(self):
        payment = FakePayment(status=PaymentStatus.NEW)
        create_payment_machine(payment)
        processor = _make_processor(payment=payment)

        data = _webhook_data(event_type="unknownEventType")
        await processor.handle_callback(data=data, headers={})

        assert payment.status == PaymentStatus.NEW

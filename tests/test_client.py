import uuid

import pytest
from getpaid_core.exceptions import CommunicationError

from getpaid_elavon.client import ElavonClient


SANDBOX_URL = "https://uat.api.test.eu.elavonaws.com"


class TestCreateOrder:
    async def test_create_order_success(self, respx_mock):
        order_response = {
            "href": f"{SANDBOX_URL}/orders/test-order-123",
            "id": "test-order-123",
            "orderReference": "order-123",
            "total": {
                "currencyCode": "PLN",
                "amount": "100.00",
            },
        }
        respx_mock.post(f"{SANDBOX_URL}/orders").respond(
            json=order_response,
            status_code=201,
        )

        client = ElavonClient(
            merchant_alias_id="test_merchant",
            secret_key="test_secret",
            sandbox=True,
        )

        result = await client.create_order(
            order_reference="order-123",
            total_amount="100.00",
            currency_code="PLN",
            description="Test order",
            items=[
                {
                    "total": {
                        "amount": "1",
                        "currencyCode": "PLN",
                    },
                    "description": "Test Product",
                }
            ],
            custom_reference=uuid.uuid4(),
        )

        assert result["id"] == "test-order-123"
        assert result["href"] == f"{SANDBOX_URL}/orders/test-order-123"

    async def test_create_order_failure_raises(self, respx_mock):
        respx_mock.post(f"{SANDBOX_URL}/orders").respond(
            json={"error": "Invalid request"},
            status_code=400,
        )

        client = ElavonClient(
            merchant_alias_id="test_merchant",
            secret_key="test_secret",
            sandbox=True,
        )

        with pytest.raises(CommunicationError, match="Error creating Elavon order"):
            await client.create_order(
                order_reference="order-123",
                total_amount="100.00",
                currency_code="PLN",
                description="Test order",
                items=[],
                custom_reference=uuid.uuid4(),
            )


class TestCreatePaymentSession:
    async def test_create_payment_session_success(self, respx_mock):
        session_response = {
            "href": f"{SANDBOX_URL}/payment-sessions/session-123",
            "id": "session-123",
            "url": "https://hpp.elavon.com/pay/session-123",
        }
        respx_mock.post(f"{SANDBOX_URL}/payment-sessions").respond(
            json=session_response,
            status_code=201,
        )

        client = ElavonClient(
            merchant_alias_id="test_merchant",
            secret_key="test_secret",
            sandbox=True,
        )

        buyer_info = {
            "email": "buyer@example.com",
            "phone": "+48123456789",
            "billing": {
                "countryCode": "PL",
                "company": "Test Company",
                "street1": "Test Street 1",
                "city": "Warsaw",
                "postalCode": "00-001",
            },
        }

        result = await client.create_payment_session(
            elavon_order_url=f"{SANDBOX_URL}/orders/test-order-123",
            return_url="https://shop.example.com/success",
            cancel_url="https://shop.example.com/cancel",
            custom_reference="payment-123",
            buyer_info=buyer_info,
        )

        assert result["id"] == "session-123"
        assert result["url"] == "https://hpp.elavon.com/pay/session-123"

    async def test_create_payment_session_failure_raises(self, respx_mock):
        respx_mock.post(f"{SANDBOX_URL}/payment-sessions").respond(
            json={"error": "Invalid order"},
            status_code=400,
        )

        client = ElavonClient(
            merchant_alias_id="test_merchant",
            secret_key="test_secret",
            sandbox=True,
        )

        buyer_info = {"email": "buyer@example.com"}

        with pytest.raises(CommunicationError, match="Error creating Elavon payment session"):
            await client.create_payment_session(
                elavon_order_url=f"{SANDBOX_URL}/orders/test-order-123",
                return_url="https://shop.example.com/success",
                cancel_url="https://shop.example.com/cancel",
                custom_reference="payment-123",
                buyer_info=buyer_info,
            )

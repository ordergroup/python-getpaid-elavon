from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from getpaid_core.enums import PaymentStatus
from getpaid_core.fsm import create_payment_machine


def make_mock_payment(
    *,
    payment_id: str = "test-payment-123",
    external_id: str = "",
    amount: Decimal = Decimal("100.00"),
    currency: str = "PLN",
    status: str = PaymentStatus.NEW,
) -> MagicMock:
    order = MagicMock()
    order.pk = "order-123"
    order.get_total_amount.return_value = amount
    order.get_buyer_info.return_value = {
        "email": "buyer@example.com",
        "phone": "+48123456789",
        "firstName": "John",
        "lastName": "Doe",
        "billing": {
            "countryCode": "PL",
            "company": "Test Company",
            "street1": "Test Street 1",
            "city": "Warsaw",
            "postalCode": "00-001",
        },
    }
    order.get_description.return_value = "Test order"
    order.get_currency.return_value = currency
    order.get_items.return_value = [{"name": "Test Product", "quantity": 1, "unit_price": amount}]
    order.get_return_url.return_value = "https://shop.example.com/success"

    payment = MagicMock()
    payment.id = payment_id
    payment.order = order
    payment.amount_required = amount
    payment.currency = currency
    payment.status = status
    payment.backend = "elavon"
    payment.external_id = external_id
    payment.description = "Test order"
    payment.amount_paid = Decimal("0")
    payment.amount_locked = Decimal("0")
    payment.amount_refunded = Decimal("0")
    payment.fraud_status = "unknown"
    payment.fraud_message = ""

    payment.is_fully_paid.return_value = True
    payment.is_fully_refunded.return_value = False

    return payment


class FakePayment:
    def __init__(
        self,
        *,
        payment_id: str = "test-payment-123",
        external_id: str = "",
        amount: Decimal = Decimal("100.00"),
        currency: str = "PLN",
        status: str = PaymentStatus.NEW,
        is_fully_paid: bool = True,
        is_fully_refunded: bool = False,
    ) -> None:
        self.id = payment_id
        self.order = MagicMock()
        self.order.pk = "order-123"
        self.order.get_total_amount.return_value = amount
        self.order.get_buyer_info.return_value = {
            "email": "buyer@example.com",
            "phone": "+48123456789",
            "firstName": "John",
            "lastName": "Doe",
            "billing": {
                "countryCode": "PL",
                "company": "Test Company",
                "street1": "Test Street 1",
                "city": "Warsaw",
                "postalCode": "00-001",
            },
        }
        self.order.get_description.return_value = "Test order"
        self.order.get_currency.return_value = currency
        self.order.get_items.return_value = [
            {
                "name": "Test Product",
                "quantity": 1,
                "unit_price": amount,
            }
        ]
        self.order.get_return_url.return_value = "https://shop.example.com/success"
        self.amount_required = amount
        self.currency = currency
        self.status = status
        self.backend = "elavon"
        self.external_id = external_id
        self.description = "Test order"
        self.amount_paid = Decimal("0")
        self.amount_locked = Decimal("0")
        self.amount_refunded = Decimal("0")
        self.fraud_status = "unknown"
        self.fraud_message = ""
        self._is_fully_paid = is_fully_paid
        self._is_fully_refunded = is_fully_refunded

    def is_fully_paid(self) -> bool:
        return self._is_fully_paid

    def is_fully_refunded(self) -> bool:
        return self._is_fully_refunded


@pytest.fixture
def mock_payment():
    return make_mock_payment()


@pytest.fixture
def mock_payment_with_fsm():
    payment = FakePayment()
    create_payment_machine(payment)
    return payment


ELAVON_CONFIG = {
    "merchant_alias_id": "test_merchant_123",
    "secret_key": "test_secret_key_456",
    "webhook_shared_secret": "Kw==",
    "webhook_signer_id": "4x3",
    "sandbox": True,
}


@pytest.fixture
def elavon_config():
    return ELAVON_CONFIG.copy()

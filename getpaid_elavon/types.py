import enum
from typing import TypedDict


class PaymentStatus(enum.StrEnum):
    SALE_AUTHORIZED = "saleAuthorized"
    SALE_DECLINED = "saleDeclined"
    SALE_AUTHORIZATION_PENDING = "saleAuthorizationPending"
    RESET = "reset"
    EXPIRED = "expired"


class BillingData(TypedDict):
    countryCode: str | None
    company: str | None
    street1: str | None
    city: str | None
    postalCode: str | None


class BuyerData(TypedDict):
    email: str
    phone: str | None
    firstName: str | None
    lastName: str | None
    billing: BillingData | None

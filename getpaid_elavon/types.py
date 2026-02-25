from enum import Enum
from typing import TypedDict


class PaymentStatus(str, Enum):
    SALE_AUTHORIZED = "saleAuthorized"
    SALE_DECLINED = "saleDeclined"
    SALE_AUTHORIZATION_PENDING = "saleAuthorizationPending"
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

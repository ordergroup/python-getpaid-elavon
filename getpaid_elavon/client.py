import base64
import uuid

import requests

from getpaid_elavon.types import BillingData, BuyerData


class Client:
    def __init__(self, merchant_alias_id: str, secret_key: str, sandbox: bool = True):
        self.merchant_alias_id = merchant_alias_id
        self.secret_key = secret_key
        self.sandbox = sandbox
        self.sandbox_url = "https://uat.api.converge.eu.elavonaws.com"
        self.production_url = "https://api.eu.elavonpayments.com"

    def get_baseurl(self) -> str:
        return self.sandbox_url if self.sandbox else self.production_url

    def create_order(
        self,
        order_reference: str,
        total_amount: str,
        currency_code: str,
        description: str,
        items: list[dict],
        custom_reference: uuid.UUID,
    ) -> dict:
        """
        Create an order on Elavon Payment Gateway.

        Args:
            order_reference: Order reference identifier
            total_amount: Total amount as string (e.g., "100.00")
            currency_code: Currency code (e.g., "USD", "EUR")
            description: Order description
            items: List of items, each with 'total'
            (dict with 'amount' and 'currencyCode') and 'description'
            custom_reference: Custom reference (payment id : uuid) for the order

        Returns:
            Dict containing order details including 'id' and 'url'
        """
        payload = {
            "orderReference": order_reference,
            "total": {
                "currencyCode": currency_code,
                "amount": total_amount,
            },
            "description": description,
            "items": items,
            "customReference": str(custom_reference),
        }
        url = f"{self.get_baseurl()}/orders"
        response = requests.post(url, json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()

    def create_payment_session(
        self,
        elavon_order_url: str,
        return_url: str,
        cancel_url: str,
        custom_reference: uuid.UUID,
        buyer_info: BuyerData,
    ) -> dict:
        """
        Create payment session for Hosted Payments Redirect.

        Args:
            elavon_order_url: Full Elavon API URL of the order resource
                             (e.g. https://uat.api.converge.eu.elavonaws.com/orders/txdjjwg49k4pdkcyyhbpb9tffmbg)
            return_url: User redirect URL after payment success
            cancel_url: User redirect URL if payment is canceled
            custom_reference: Custom reference (payment id : uuid) for the order
            buyer_info: billing information dict with customer details

        Returns:
            Dict containing session details including 'href' URL for redirect
        """
        payload = {
            "order": elavon_order_url,
            "returnUrl": return_url,
            "cancelUrl": cancel_url,
            "doCreateTransaction": True,
            "hppType": "fullPageRedirect",
            "customReference": str(custom_reference),
            "shopperEmailAddress": buyer_info.get("email"),
        }

        bill_to = self._transform_buyer_data(buyer_info)

        if bill_to:
            payload["billTo"] = bill_to
        url = f"{self.get_baseurl()}/payment-sessions"
        response = requests.post(url, json=payload, headers=self._headers())
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _transform_buyer_data(
        buyer_info: BuyerData,
    ) -> BillingData | None:
        """
        Transform buyer data
        Args:
            buyer_info: Buyer data with nested billing information
        """
        billing = buyer_info.get("billing")
        return billing and {
            "countryCode": billing.get("countryCode"),
            "company": billing.get("company"),
            "street1": billing.get("street1"),
            "city": billing.get("city"),
            "postalCode": billing.get("postalCode"),
            "email": buyer_info.get("email", ""),
            "primaryPhone": buyer_info.get("phone"),
        }

    def _headers(self) -> dict:
        auth_string = f"{self.merchant_alias_id}:{self.secret_key}"
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        return {
            "Authorization": f"Basic {encoded_auth}",
            "Accept": "application/json",
        }

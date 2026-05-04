import base64
import uuid

import httpx
from getpaid_core.exceptions import CommunicationError

from getpaid_elavon.types import BillingData
from getpaid_elavon.types import BuyerData


class ElavonClient:
    """Async client for Elavon Payment Gateway.

    Uses httpx.AsyncClient for all HTTP communication.
    Can be used as an async context manager for connection reuse::

        async with ElavonClient(...) as client:
            await client.create_order(...)
            await client.create_payment_session(...)
    """

    last_response: httpx.Response | None = None

    def __init__(
        self,
        merchant_alias_id: str,
        secret_key: str,
        sandbox: bool = True,
    ) -> None:
        self.merchant_alias_id = merchant_alias_id
        self.secret_key = secret_key
        self.sandbox = sandbox
        self.sandbox_url = "https://uat.api.converge.eu.elavonaws.com"
        self.production_url = "https://api.eu.convergepay.com"
        self._client: httpx.AsyncClient | None = None
        self._owns_client: bool = False

    async def __aenter__(self) -> "ElavonClient":
        self._client = httpx.AsyncClient()
        self._owns_client = True
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
            self._owns_client = False

    def get_baseurl(self) -> str:
        return self.sandbox_url if self.sandbox else self.production_url

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_data: dict | None = None,
        follow_redirects: bool = True,
    ) -> httpx.Response:
        """Execute an HTTP request, handling client lifecycle.

        Stores response in self.last_response for debugging.
        """
        if self._client is not None:
            self.last_response = await self._client.request(
                method,
                url,
                headers=headers,
                json=json_data,
                follow_redirects=follow_redirects,
            )
        else:
            async with httpx.AsyncClient() as client:
                self.last_response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_data,
                    follow_redirects=follow_redirects,
                )
        return self.last_response

    async def create_order(
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
        response = await self._request(
            "POST",
            url,
            headers=self._headers(),
            json_data=payload,
        )

        if response.status_code not in [200, 201]:
            raise CommunicationError(
                "Error creating Elavon order",
                context={"raw_response": self.last_response},
            )
        return response.json()

    async def create_payment_session(
        self,
        elavon_order_url: str,
        return_url: str,
        cancel_url: str,
        custom_reference: str,
        buyer_info: BuyerData,
    ) -> dict:
        """
        Create payment session for Hosted Payments Redirect.

        Args:
            elavon_order_url: Full Elavon API URL of the order resource
                             (e.g. https://uat.api.converge.eu.elavonaws.com/orders/txdjjwg49k4pdkcyyhbpb9tffmbg)
            return_url: User redirect URL after payment success
            cancel_url: User redirect URL if payment is canceled
            custom_reference: Custom reference (payment id : str) for the order
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
        response = await self._request(
            "POST",
            url,
            headers=self._headers(),
            json_data=payload,
        )

        if response.status_code not in [200, 201]:
            raise CommunicationError(
                f"Error creating Elavon payment session raw_response : {self.last_response}",
            )

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

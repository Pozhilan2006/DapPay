from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings, get_settings


class PayPalAuthenticationError(RuntimeError):
    """Raised when PayPal OAuth authentication cannot be completed."""


class PayPalConfigurationError(PayPalAuthenticationError):
    """Raised when the PayPal OAuth credentials are not configured."""


class PayPalApiError(RuntimeError):
    """Raised when a PayPal Orders API request cannot be completed."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class OAuthToken:
    access_token: str = field(repr=False)
    token_type: str
    expires_in: int


class PayPalClient:
    """Client for PayPal OAuth authentication."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client
        self._timeout = timeout

    def get_base_url(self) -> str:
        return self.settings.paypal_base_url

    def is_configured(self) -> bool:
        return bool(self.settings.paypal_client_id and self.settings.paypal_client_secret)

    def get_access_token(self) -> OAuthToken:
        if not self.is_configured():
            raise PayPalConfigurationError(
                "PayPal client credentials are not configured."
            )

        if self._http_client is not None:
            return self._request_access_token(self._http_client)

        with httpx.Client(timeout=self._timeout) as http_client:
            return self._request_access_token(http_client)

    def post_orders_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        request_id: str,
    ) -> Any:
        if not self.is_configured():
            raise PayPalConfigurationError(
                "PayPal client credentials are not configured."
            )
        if (
            endpoint != "orders"
            and re.fullmatch(r"orders/[A-Za-z0-9_-]{1,128}/capture", endpoint)
            is None
        ):
            raise ValueError("Invalid PayPal Orders API endpoint.")

        if self._http_client is not None:
            return self._post_orders_request(
                self._http_client, endpoint, payload, request_id
            )

        with httpx.Client(timeout=self._timeout) as http_client:
            return self._post_orders_request(
                http_client, endpoint, payload, request_id
            )

    def get_order_request(self, order_id: str) -> Any:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", order_id):
            raise ValueError("Invalid PayPal order ID.")
        if not self.is_configured():
            raise PayPalConfigurationError(
                "PayPal client credentials are not configured."
            )

        if self._http_client is not None:
            return self._get_order_request(self._http_client, order_id)

        with httpx.Client(timeout=self._timeout) as http_client:
            return self._get_order_request(http_client, order_id)

    def verify_webhook_signature(
        self,
        transmission_headers: dict[str, str],
        webhook_event: dict[str, Any],
    ) -> bool:
        webhook_id = self.settings.paypal_webhook_id
        if not webhook_id:
            raise PayPalConfigurationError("PayPal webhook ID is not configured.")
        if not self.is_configured():
            raise PayPalConfigurationError(
                "PayPal client credentials are not configured."
            )

        payload = {
            "auth_algo": transmission_headers["paypal-auth-algo"],
            "cert_url": transmission_headers["paypal-cert-url"],
            "transmission_id": transmission_headers["paypal-transmission-id"],
            "transmission_sig": transmission_headers["paypal-transmission-sig"],
            "transmission_time": transmission_headers["paypal-transmission-time"],
            "webhook_id": webhook_id,
            "webhook_event": webhook_event,
        }
        if self._http_client is not None:
            return self._verify_webhook_signature(self._http_client, payload)

        with httpx.Client(timeout=self._timeout) as http_client:
            return self._verify_webhook_signature(http_client, payload)

    def _verify_webhook_signature(
        self, http_client: httpx.Client, payload: dict[str, Any]
    ) -> bool:
        token = self._request_access_token(http_client)
        try:
            response = http_client.post(
                f"{self.get_base_url().rstrip('/')}/v1/notifications/verify-webhook-signature",
                json=payload,
                headers={"Authorization": f"Bearer {token.access_token}"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise PayPalApiError(
                "PayPal webhook verification request timed out."
            ) from None
        except httpx.RequestError:
            raise PayPalApiError(
                "Unable to connect to PayPal webhook verification."
            ) from None

        if response.status_code == 401:
            raise PayPalApiError(
                "PayPal rejected the access token; authentication may have expired.",
                status_code=401,
            )
        if response.is_error:
            raise PayPalApiError(
                "PayPal webhook verification request failed.",
                status_code=response.status_code,
            )
        try:
            result = response.json()
        except ValueError:
            raise PayPalApiError(
                "PayPal returned an invalid webhook verification response.",
                status_code=response.status_code,
            ) from None
        return (
            isinstance(result, dict)
            and result.get("verification_status") == "SUCCESS"
        )

    def _get_order_request(
        self, http_client: httpx.Client, order_id: str
    ) -> Any:
        token = self._request_access_token(http_client)
        try:
            response = http_client.get(
                f"{self.get_base_url().rstrip('/')}/v2/checkout/orders/{order_id}",
                headers={"Authorization": f"Bearer {token.access_token}"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise PayPalApiError("PayPal order retrieval request timed out.") from None
        except httpx.RequestError:
            raise PayPalApiError(
                "Unable to connect to the PayPal Orders API."
            ) from None

        if response.status_code == 401:
            raise PayPalApiError(
                "PayPal rejected the access token; authentication may have expired.",
                status_code=401,
            )
        if response.is_error:
            raise PayPalApiError(
                "PayPal order retrieval request failed.",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError:
            raise PayPalApiError(
                "PayPal Orders API returned an invalid response.",
                status_code=response.status_code,
            ) from None

    def _post_orders_request(
        self,
        http_client: httpx.Client,
        endpoint: str,
        payload: dict[str, Any],
        request_id: str,
    ) -> Any:
        token = self._request_access_token(http_client)
        try:
            response = http_client.post(
                f"{self.get_base_url().rstrip('/')}/v2/checkout/{endpoint}",
                json=payload,
                headers={
                    "Authorization": f"Bearer {token.access_token}",
                    "PayPal-Request-Id": request_id,
                },
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise PayPalApiError("PayPal Orders API request timed out.") from None
        except httpx.RequestError:
            raise PayPalApiError(
                "Unable to connect to the PayPal Orders API."
            ) from None

        if response.status_code == 401:
            raise PayPalApiError(
                "PayPal rejected the access token; authentication may have expired.",
                status_code=401,
            )
        if response.is_error:
            raise PayPalApiError(
                "PayPal Orders API request failed.",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError:
            raise PayPalApiError(
                "PayPal Orders API returned an invalid response.",
                status_code=response.status_code,
            ) from None

    def _request_access_token(self, http_client: httpx.Client) -> OAuthToken:
        try:
            response = http_client.post(
                f"{self.get_base_url().rstrip('/')}/v1/oauth2/token",
                auth=(
                    self.settings.paypal_client_id,
                    self.settings.paypal_client_secret,
                ),
                data={"grant_type": "client_credentials"},
                timeout=self._timeout,
            )
        except httpx.TimeoutException:
            raise PayPalAuthenticationError(
                "PayPal authentication request timed out."
            ) from None
        except httpx.RequestError:
            raise PayPalAuthenticationError(
                "Unable to connect to PayPal for authentication."
            ) from None

        if response.status_code == 401:
            raise PayPalAuthenticationError(
                "PayPal rejected the client credentials."
            )
        if response.status_code >= 500:
            raise PayPalAuthenticationError(
                "PayPal authentication service returned a server error."
            )
        if response.is_error:
            raise PayPalAuthenticationError(
                "PayPal authentication request failed."
            )

        try:
            payload = response.json()
        except ValueError:
            raise PayPalAuthenticationError(
                "PayPal returned an invalid authentication response."
            ) from None

        return self._parse_token_response(payload)

    @staticmethod
    def _parse_token_response(payload: Any) -> OAuthToken:
        if not isinstance(payload, dict):
            raise PayPalAuthenticationError(
                "PayPal returned an invalid authentication response."
            )

        access_token = payload.get("access_token")
        token_type = payload.get("token_type")
        expires_in = payload.get("expires_in")

        if (
            not isinstance(access_token, str)
            or not access_token.strip()
            or not isinstance(token_type, str)
            or not token_type.strip()
            or not isinstance(expires_in, int)
            or isinstance(expires_in, bool)
            or expires_in <= 0
        ):
            raise PayPalAuthenticationError(
                "PayPal returned an invalid authentication response."
            )

        return OAuthToken(
            access_token=access_token,
            token_type=token_type,
            expires_in=expires_in,
        )

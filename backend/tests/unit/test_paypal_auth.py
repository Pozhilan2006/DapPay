from contextlib import contextmanager
from types import SimpleNamespace
from typing import Callable, Generator
from urllib.parse import parse_qs

import httpx
import pytest

from app.core.config import Settings
from app.integrations.paypal.client import (
    OAuthToken,
    PayPalAuthenticationError,
    PayPalClient,
    PayPalConfigurationError,
)
from scripts import verify_paypal_auth

ResponseHandler = Callable[[httpx.Request], httpx.Response]


def _settings(**overrides: str) -> Settings:
    values = {
        "PAYPAL_CLIENT_ID": "test-client-id",
        "PAYPAL_CLIENT_SECRET": "test-client-secret",
        "PAYPAL_BASE_URL": "https://api-m.sandbox.paypal.com",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@contextmanager
def _paypal_client(
    handler: ResponseHandler,
    settings: Settings | None = None,
) -> Generator[PayPalClient, None, None]:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        yield PayPalClient(settings=settings or _settings(), http_client=http_client)
    finally:
        http_client.close()


def test_successful_oauth_token_response_uses_client_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == (
            "https://api-m.sandbox.paypal.com/v1/oauth2/token"
        )
        assert request.headers["authorization"] == (
            "Basic dGVzdC1jbGllbnQtaWQ6dGVzdC1jbGllbnQtc2VjcmV0"
        )
        assert parse_qs(request.content.decode()) == {
            "grant_type": ["client_credentials"]
        }
        return httpx.Response(
            200,
            json={
                "access_token": "private-access-token",
                "token_type": "Bearer",
                "expires_in": 28799,
            },
        )

    with _paypal_client(handler) as client:
        token = client.get_access_token()

    assert token == OAuthToken(
        access_token="private-access-token",
        token_type="Bearer",
        expires_in=28799,
    )
    assert "private-access-token" not in repr(token)


def test_invalid_client_credentials_return_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(401, json={"error": "invalid_client"})

    with _paypal_client(handler) as client:
        with pytest.raises(
            PayPalAuthenticationError, match="rejected the client credentials"
        ) as error:
            client.get_access_token()

    assert "test-client-secret" not in str(error.value)


def test_paypal_server_errors_return_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(503, json={"error": "unavailable"})

    with _paypal_client(handler) as client:
        with pytest.raises(PayPalAuthenticationError, match="server error"):
            client.get_access_token()


def test_connection_timeout_returns_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("sensitive transport details", request=request)

    with _paypal_client(handler) as client:
        with pytest.raises(
            PayPalAuthenticationError, match="request timed out"
        ) as error:
            client.get_access_token()

    assert "sensitive transport details" not in str(error.value)


def test_connection_error_returns_safe_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sensitive transport details", request=request)

    with _paypal_client(handler) as client:
        with pytest.raises(
            PayPalAuthenticationError, match="Unable to connect to PayPal"
        ) as error:
            client.get_access_token()

    assert "sensitive transport details" not in str(error.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"access_token": "private-access-token"}),
        httpx.Response(
            200,
            json={
                "access_token": "private-access-token",
                "token_type": "Bearer",
                "expires_in": "one hour",
            },
        ),
    ],
)
def test_malformed_token_response_returns_safe_error(response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return response

    with _paypal_client(handler) as client:
        with pytest.raises(
            PayPalAuthenticationError, match="invalid authentication response"
        ) as error:
            client.get_access_token()

    assert "private-access-token" not in str(error.value)


def test_missing_environment_configuration_does_not_make_request():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        pytest.fail("OAuth request must not be sent without configured credentials")

    with _paypal_client(
        handler,
        settings=_settings(PAYPAL_CLIENT_ID="", PAYPAL_CLIENT_SECRET=""),
    ) as client:
        with pytest.raises(
            PayPalConfigurationError, match="credentials are not configured"
        ):
            client.get_access_token()


def test_verification_command_prints_expiry_without_access_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    token = OAuthToken(
        access_token="private-access-token",
        token_type="Bearer",
        expires_in=28799,
    )
    client = SimpleNamespace(get_access_token=lambda: token)
    monkeypatch.setattr(verify_paypal_auth, "PayPalClient", lambda: client)

    assert verify_paypal_auth.main() == 0
    output = capsys.readouterr().out
    assert "authentication succeeded" in output
    assert "28799 seconds" in output
    assert "private-access-token" not in output

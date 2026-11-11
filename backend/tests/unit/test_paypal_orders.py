from contextlib import contextmanager
from decimal import Decimal
from typing import Callable, Generator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.api.routes import paypal as paypal_routes
from app.integrations.paypal.client import PayPalApiError, PayPalClient
from app.integrations.paypal.orders import capture_order, create_order, get_order
from app.schemas.paypal import CreatePayPalOrderRequest

ResponseHandler = Callable[[httpx.Request], httpx.Response]


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        PAYPAL_CLIENT_ID="test-client-id",
        PAYPAL_CLIENT_SECRET="test-client-secret",
        PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com",
    )


@contextmanager
def _client(handler: ResponseHandler) -> Generator[PayPalClient, None, None]:
    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        yield PayPalClient(
            settings=_settings(), http_client=http_client, timeout=1.25
        )
    finally:
        http_client.close()


def _token_response(request: httpx.Request) -> httpx.Response:
    assert str(request.url) == "https://api-m.sandbox.paypal.com/v1/oauth2/token"
    assert request.method == "POST"
    return httpx.Response(
        200,
        json={
            "access_token": "private-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )


def test_create_order_uses_capture_intent_decimal_amount_and_request_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)

        assert request.method == "POST"
        assert request.url.path == "/v2/checkout/orders"
        assert request.headers["authorization"] == "Bearer private-access-token"
        assert request.headers["paypal-request-id"]
        assert request.extensions["timeout"]["read"] == 1.25
        assert request.read() == (
            b'{"intent":"CAPTURE","purchase_units":[{"amount":'
            b'{"currency_code":"USD","value":"12345678901234567890.01"},'
            b'"custom_id":"merchant-42"}],"application_context":'
            b'{"return_url":"https://merchant.example/return",'
            b'"cancel_url":"https://merchant.example/cancel"}}'
        )
        return httpx.Response(
            201,
            json={
                "id": "ORDER-123",
                "status": "CREATED",
                "links": [
                    {
                        "rel": "payer-action",
                        "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER-123",
                    }
                ],
            },
        )

    with _client(handler) as paypal:
        order = create_order(
            amount=Decimal("12345678901234567890.01"),
            currency="usd",
            merchant_reference="merchant-42",
            return_url="https://merchant.example/return",
            cancel_url="https://merchant.example/cancel",
            client=paypal,
        )

    assert order.order_id == "ORDER-123"
    assert order.status == "CREATED"
    assert order.approval_url.startswith("https://www.sandbox.paypal.com/")


def test_capture_order_returns_capture_details_and_request_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)

        assert request.url.path == "/v2/checkout/orders/ORDER-123/capture"
        assert request.headers["authorization"] == "Bearer private-access-token"
        assert request.headers["paypal-request-id"]
        assert request.read() == b"{}"
        return httpx.Response(
            201,
            json={
                "id": "ORDER-123",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAPTURE-456",
                                    "status": "COMPLETED",
                                    "amount": {
                                        "value": "123.45",
                                        "currency_code": "USD",
                                    },
                                    "create_time": "2026-11-10T12:13:14Z",
                                    "update_time": "2026-11-10T12:13:15Z",
                                }
                            ]
                        }
                    }
                ],
            },
        )

    with _client(handler) as paypal:
        capture = capture_order("ORDER-123", client=paypal)

    assert capture.order_id == "ORDER-123"
    assert capture.capture_id == "CAPTURE-456"
    assert capture.status == "COMPLETED"
    assert capture.amount == Decimal("123.45")
    assert capture.currency == "USD"
    assert capture.create_time is not None
    assert capture.update_time is not None


@pytest.mark.parametrize("amount", [Decimal("0"), Decimal("-1"), Decimal("NaN")])
def test_create_order_rejects_invalid_amount_without_api_request(amount: Decimal):
    with pytest.raises(ValueError, match="finite positive decimal"):
        create_order(
            amount=amount,
            currency="USD",
            merchant_reference="merchant-42",
            return_url="https://merchant.example/return",
            cancel_url="https://merchant.example/cancel",
        )


def test_create_order_rejects_float_amount():
    with pytest.raises(ValueError, match="must be a Decimal"):
        create_order(
            amount=10.25,  # type: ignore[arg-type]
            currency="USD",
            merchant_reference="merchant-42",
            return_url="https://merchant.example/return",
            cancel_url="https://merchant.example/cancel",
        )


@pytest.mark.parametrize("currency", ["US", "USDD", "U$D", ""])
def test_create_order_rejects_invalid_currency(currency: str):
    with pytest.raises(ValueError, match="three-letter"):
        create_order(
            amount=Decimal("10.00"),
            currency=currency,
            merchant_reference="merchant-42",
            return_url="https://merchant.example/return",
            cancel_url="https://merchant.example/cancel",
        )


def test_invalid_access_token_is_reported_without_exposing_response():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        return httpx.Response(401, json={"error": "invalid_token"})

    with _client(handler) as paypal:
        with pytest.raises(PayPalApiError, match="authentication may have expired") as error:
            create_order(
                amount=Decimal("10.00"),
                currency="USD",
                merchant_reference="merchant-42",
                return_url="https://merchant.example/return",
                cancel_url="https://merchant.example/cancel",
                client=paypal,
            )

    assert "private-access-token" not in str(error.value)
    assert "invalid_token" not in str(error.value)


@pytest.mark.parametrize("status_code", [400, 403, 422, 500, 503])
def test_paypal_api_errors_are_reported_safely(status_code: int):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        return httpx.Response(status_code, json={"name": "SENSITIVE"})

    with _client(handler) as paypal:
        with pytest.raises(PayPalApiError) as error:
            create_order(
                amount=Decimal("10.00"),
                currency="USD",
                merchant_reference="merchant-42",
                return_url="https://merchant.example/return",
                cancel_url="https://merchant.example/cancel",
                client=paypal,
            )

    assert "SENSITIVE" not in str(error.value)


def test_orders_api_timeout_is_reported_safely():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        raise httpx.ReadTimeout("private transport detail", request=request)

    with _client(handler) as paypal:
        with pytest.raises(PayPalApiError, match="timed out") as error:
            create_order(
                amount=Decimal("10.00"),
                currency="USD",
                merchant_reference="merchant-42",
                return_url="https://merchant.example/return",
                cancel_url="https://merchant.example/cancel",
                client=paypal,
            )

    assert "private transport detail" not in str(error.value)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(201, content=b"not-json"),
        httpx.Response(201, json={"id": "ORDER-123", "status": "CREATED"}),
        httpx.Response(
            201,
            json={
                "id": "ORDER-123",
                "status": "CREATED",
                "links": [{"rel": "approve", "href": "https://evil.example/"}],
            },
        ),
    ],
)
def test_malformed_order_responses_are_rejected(response: httpx.Response):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        return response

    with _client(handler) as paypal:
        with pytest.raises(PayPalApiError):
            create_order(
                amount=Decimal("10.00"),
                currency="USD",
                merchant_reference="merchant-42",
                return_url="https://merchant.example/return",
                cancel_url="https://merchant.example/cancel",
                client=paypal,
            )


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "ORDER-123"},
        {
            "id": "OTHER-ORDER",
            "purchase_units": [{"payments": {"captures": []}}],
        },
        {
            "id": "ORDER-123",
            "purchase_units": [{"payments": {"captures": []}}],
        },
        {
            "id": "ORDER-123",
            "purchase_units": [
                {
                    "payments": {
                        "captures": [
                            {
                                "id": "CAPTURE-456",
                                "status": "COMPLETED",
                                "amount": {"value": "not-money", "currency_code": "USD"},
                            }
                        ]
                    }
                }
            ],
        },
    ],
)
def test_malformed_capture_response_is_rejected(payload: dict[str, object]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        return httpx.Response(201, json=payload)

    with _client(handler) as paypal:
        with pytest.raises(PayPalApiError, match="invalid capture response"):
            capture_order("ORDER-123", client=paypal)


@pytest.mark.parametrize(
    "payload",
    [
        {"amount": 1.25, "currency": "USD"},
        {"amount": "0", "currency": "USD"},
        {"amount": "10.00", "currency": "US"},
        {"amount": "10.00", "currency": "USD"},
    ],
)
def test_create_request_schema_rejects_invalid_checkout_fields(
    payload: dict[str, object],
):
    checkout = {
        **payload,
        "merchant_reference": "merchant-42",
        "return_url": "https://merchant.example/return",
        "cancel_url": "https://merchant.example/cancel",
    }
    if payload.get("amount") == "10.00" and payload.get("currency") == "USD":
        checkout["return_url"] = "file:///etc/passwd"
    with pytest.raises(ValueError):
        CreatePayPalOrderRequest.model_validate(checkout)


def test_paypal_order_api_endpoints_return_safe_response_models(
    monkeypatch: pytest.MonkeyPatch,
    api_client: TestClient,
):
    class MockPayPalClient:
        def post_orders_request(
            self, endpoint: str, payload: dict[str, object], request_id: str
        ) -> dict[str, object]:
            assert request_id
            if endpoint == "orders":
                assert payload["intent"] == "CAPTURE"
                return {
                    "id": "ORDER-123",
                    "status": "CREATED",
                    "links": [
                        {
                            "rel": "approve",
                            "href": "https://www.sandbox.paypal.com/checkoutnow",
                        }
                    ],
                }
            return {
                "id": "ORDER-123",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAPTURE-456",
                                    "status": "COMPLETED",
                                    "amount": {
                                        "value": "10.00",
                                        "currency_code": "USD",
                                    },
                                }
                            ]
                        }
                    }
                ],
            }

    monkeypatch.setattr(paypal_routes, "PayPalClient", MockPayPalClient)
    create_response = api_client.post(
        "/api/paypal/orders",
        json={
            "amount": "10.00",
            "currency": "USD",
            "invoice_id": "invoice-42",
            "return_url": "https://merchant.example/return",
            "cancel_url": "https://merchant.example/cancel",
        },
    )
    capture_response = api_client.post("/api/paypal/orders/ORDER-123/capture")

    assert create_response.status_code == 201
    assert create_response.json() == {
        "order_id": "ORDER-123",
        "status": "CREATED",
        "approval_url": "https://www.sandbox.paypal.com/checkoutnow",
    }
    assert capture_response.status_code == 200
    assert capture_response.json() == {
        "order_id": "ORDER-123",
        "capture_id": "CAPTURE-456",
        "capture_status": "COMPLETED",
        "captured_amount": "10.00",
        "currency": "USD",
        "create_time": None,
        "update_time": None,
    }
    assert api_client.get("/api/orders").json()[0]["order_id"] == "ORDER-123"
    assert api_client.get("/api/payments").json()[0]["payment_id"] == "CAPTURE-456"
    assert (
        api_client.get("/api/payments/CAPTURE-456").json()["status"] == "COMPLETED"
    )


@pytest.mark.parametrize(
    ("amount", "currency"),
    [(0, "USD"), ("10.00", "US")],
)
def test_paypal_order_api_rejects_invalid_amount_and_currency(
    amount: object,
    currency: str,
    api_client: TestClient,
):
    response = api_client.post(
        "/api/paypal/orders",
        json={
            "amount": amount,
            "currency": currency,
            "merchant_reference": "merchant-42",
            "return_url": "https://merchant.example/return",
            "cancel_url": "https://merchant.example/cancel",
        },
    )

    assert response.status_code == 422


def test_get_order_uses_authenticated_get_request_and_returns_safe_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        assert request.method == "GET"
        assert request.url.path == "/v2/checkout/orders/ORDER-123"
        assert request.headers["authorization"] == "Bearer private-access-token"
        assert request.extensions["timeout"]["read"] == 1.25
        return httpx.Response(
            200,
            json={
                "id": "ORDER-123",
                "status": "CREATED",
                "intent": "CAPTURE",
                "create_time": "2026-11-10T12:13:14Z",
                "update_time": "2026-11-10T12:13:15Z",
                "payer": {"email_address": "buyer@example.test"},
                "payment_source": {"paypal": {"email_address": "buyer@example.test"}},
                "purchase_units": [
                    {
                        "custom_id": "merchant-42",
                        "invoice_id": "invoice-42",
                        "amount": {"value": "25.50", "currency_code": "USD"},
                        "payee": {
                            "merchant_id": "MERCHANT-456",
                            "email_address": "seller@example.test",
                        },
                        "payments": {
                            "captures": [
                                {"id": "CAPTURE-789", "status": "COMPLETED"}
                            ]
                        },
                    }
                ],
            },
        )

    with _client(handler) as paypal:
        order = get_order("ORDER-123", client=paypal)

    assert order.status == "CREATED"
    assert order.intent == "CAPTURE"
    assert order.purchase_units[0].merchant_reference == "merchant-42"
    assert order.purchase_units[0].amount == Decimal("25.50")
    assert order.purchase_units[0].currency == "USD"
    assert order.purchase_units[0].has_payee is True
    assert order.purchase_units[0].captures[0].capture_id == "CAPTURE-789"
    assert order.payment_source_types == ("paypal",)
    assert "buyer@example.test" not in repr(order)
    assert "seller@example.test" not in repr(order)


@pytest.mark.parametrize("order_id", ["", "../secrets", "https://evil.example/x"])
def test_get_order_rejects_invalid_id_without_request(order_id: str):
    with pytest.raises(ValueError, match="Invalid PayPal order ID"):
        get_order(order_id)


@pytest.mark.parametrize(
    ("response", "error_text"),
    [
        (httpx.Response(401, json={"error": "invalid_token"}), "authentication may have expired"),
        (httpx.Response(404, json={"debug_id": "private-debug-id"}), "retrieval request failed"),
        (httpx.Response(200, content=b"not-json"), "invalid response"),
    ],
)
def test_get_order_sanitizes_http_and_json_errors(
    response: httpx.Response,
    error_text: str,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        return response

    with _client(handler) as paypal:
        with pytest.raises(PayPalApiError, match=error_text) as error:
            paypal.get_order_request("ORDER-123")

    assert "private-access-token" not in str(error.value)
    assert "private-debug-id" not in str(error.value)


def test_get_order_timeout_is_sanitized():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return _token_response(request)
        raise httpx.ReadTimeout("private transport detail", request=request)

    with _client(handler) as paypal:
        with pytest.raises(PayPalApiError, match="retrieval request timed out") as error:
            paypal.get_order_request("ORDER-123")

    assert "private transport detail" not in str(error.value)


def test_get_order_api_response_does_not_expose_payer_details(
    monkeypatch: pytest.MonkeyPatch,
    api_client: TestClient,
):
    class MockPayPalClient:
        def get_order_request(self, order_id: str) -> dict[str, object]:
            assert order_id == "ORDER-123"
            return {
                "id": order_id,
                "status": "CREATED",
                "intent": "CAPTURE",
                "create_time": "2026-11-10T12:13:14Z",
                "purchase_units": [
                    {
                        "custom_id": "merchant-42",
                        "amount": {"value": "25.50", "currency_code": "USD"},
                        "payee": {
                            "merchant_id": "MERCHANT-456",
                            "email_address": "seller@example.test",
                        },
                    }
                ],
                "payer": {"email_address": "buyer@example.test"},
                "payment_source": {
                    "paypal": {"email_address": "buyer@example.test"}
                },
            }

    monkeypatch.setattr(paypal_routes, "PayPalClient", MockPayPalClient)
    response = api_client.get("/api/paypal/orders/ORDER-123")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "CREATED"
    assert data["purchase_units"][0]["amount"] == "25.50"
    assert data["purchase_units"][0]["currency"] == "USD"
    assert data["purchase_units"][0]["has_payee"] is True
    assert data["payment_source_types"] == ["paypal"]
    assert "email_address" not in response.text
    assert "MERCHANT-456" not in response.text

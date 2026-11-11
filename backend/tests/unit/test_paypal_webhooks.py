from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.routes import webhooks as webhook_routes
from app.api.routes.orders import list_orders
from app.core.config import Settings
from app.core.security import Principal, Role
from app.integrations.paypal.client import (
    PayPalApiError,
    PayPalClient,
    PayPalConfigurationError,
)
from app.integrations.paypal.webhooks import (
    extract_transmission_headers,
    validate_webhook_signature,
)
from app.models import PaymentCapture, WebhookEvent
from app.services import paypal_webhooks
from app.services.paypal_webhooks import ingest_verified_event

SIGNATURE_HEADERS = {
    "paypal-auth-algo": "SHA256withRSA",
    "paypal-cert-url": "https://api.paypal.com/cert",
    "paypal-transmission-id": "transmission-123",
    "paypal-transmission-sig": "signature-value",
    "paypal-transmission-time": "2026-11-11T00:00:00Z",
}


def _event(
    event_id: str,
    event_type: str,
    *,
    resource: dict[str, object] | None = None,
    create_time: str = "2026-11-11T00:00:00Z",
) -> dict[str, object]:
    return {
        "id": event_id,
        "event_type": event_type,
        "resource_type": "capture",
        "create_time": create_time,
        "resource": resource or {},
    }


def _capture_event(
    event_id: str,
    event_type: str,
    *,
    capture_id: str = "CAPTURE-1",
    order_id: str = "ORDER-1",
    amount: str = "25.50",
    currency: str = "USD",
    create_time: str = "2026-11-11T00:00:00Z",
) -> dict[str, object]:
    return _event(
        event_id,
        event_type,
        create_time=create_time,
        resource={
            "id": capture_id,
            "status": event_type.rsplit(".", 1)[-1],
            "amount": {"value": amount, "currency_code": currency},
            "create_time": create_time,
            "update_time": create_time,
            "supplementary_data": {
                "related_ids": {"order_id": order_id, "capture_id": capture_id}
            },
        },
    )


class SignatureClient:
    def __init__(self, valid: bool = True):
        self.valid = valid
        self.calls = 0

    def verify_webhook_signature(
        self, headers: dict[str, str], event: dict[str, object]
    ) -> bool:
        self.calls += 1
        assert headers == SIGNATURE_HEADERS
        assert event["id"]
        return self.valid


class AuthoritativeOrderClient(PayPalClient):
    def get_order_request(self, order_id: str) -> dict[str, object]:
        return {
            "id": order_id,
            "status": "COMPLETED",
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {"value": "25.50", "currency_code": "USD"},
                    "payments": {
                        "captures": [
                            {
                                "id": "CAPTURE-1",
                                "status": "COMPLETED",
                                "amount": {
                                    "value": "25.50",
                                    "currency_code": "USD",
                                },
                                "create_time": "2026-11-11T00:00:00Z",
                                "update_time": "2026-11-11T00:00:00Z",
                            }
                        ]
                    },
                }
            ],
        }


class PendingAuthoritativeOrderClient(AuthoritativeOrderClient):
    def get_order_request(self, order_id: str) -> dict[str, object]:
        response = super().get_order_request(order_id)
        purchase_units = response["purchase_units"]
        assert isinstance(purchase_units, list)
        payment_capture = purchase_units[0]["payments"]["captures"][0]
        payment_capture["status"] = "PENDING"
        response["status"] = "APPROVED"
        return response


def test_extract_transmission_headers_rejects_missing_header():
    with pytest.raises(ValueError, match="headers are missing"):
        extract_transmission_headers({"paypal-auth-algo": "SHA256withRSA"})


def test_paypal_verification_api_uses_official_endpoint_and_result():
    settings = Settings(
        _env_file=None,
        PAYPAL_CLIENT_ID="client",
        PAYPAL_CLIENT_SECRET="secret",
        PAYPAL_WEBHOOK_ID="configured-webhook",
        PAYPAL_BASE_URL="https://api-m.sandbox.paypal.com",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "private-token",
                    "token_type": "Bearer",
                    "expires_in": 300,
                },
            )
        assert request.url.path == "/v1/notifications/verify-webhook-signature"
        assert request.headers["authorization"] == "Bearer private-token"
        body = request.read().decode()
        assert '"webhook_id":"configured-webhook"' in body
        assert '"transmission_id":"transmission-123"' in body
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        paypal = PayPalClient(settings=settings, http_client=http_client)
        assert validate_webhook_signature(
            _event("EVENT-1", "CHECKOUT.ORDER.APPROVED"),
            SIGNATURE_HEADERS,
            client=paypal,
        )


def test_missing_webhook_id_fails_safely():
    settings = Settings(
        _env_file=None,
        PAYPAL_CLIENT_ID="client",
        PAYPAL_CLIENT_SECRET="secret",
        PAYPAL_WEBHOOK_ID="",
    )
    paypal = PayPalClient(settings=settings)
    with pytest.raises(PayPalConfigurationError, match="webhook ID"):
        paypal.verify_webhook_signature(
            SIGNATURE_HEADERS,
            _event("EVENT-1", "CHECKOUT.ORDER.APPROVED"),
        )


def test_paypal_verification_failure_is_false_not_accepted():
    settings = Settings(
        _env_file=None,
        PAYPAL_CLIENT_ID="client",
        PAYPAL_CLIENT_SECRET="secret",
        PAYPAL_WEBHOOK_ID="configured-webhook",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "private-token",
                    "token_type": "Bearer",
                    "expires_in": 300,
                },
            )
        return httpx.Response(200, json={"verification_status": "FAILURE"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        paypal = PayPalClient(settings=settings, http_client=http_client)
        assert not paypal.verify_webhook_signature(
            SIGNATURE_HEADERS,
            _event("EVENT-1", "CHECKOUT.ORDER.APPROVED"),
        )


def test_successful_webhook_is_persisted_with_sensitive_fields_scrubbed(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    verifier = SignatureClient()
    monkeypatch.setattr(webhook_routes, "PayPalClient", lambda: verifier)
    payload = _event(
        "EVENT-1",
        "CHECKOUT.ORDER.APPROVED",
        resource={
            "id": "ORDER-1",
            "status": "APPROVED",
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "custom_id": "merchant-1",
                    "amount": {"value": "25.50", "currency_code": "USD"},
                    "payee": {"email_address": "seller@example.test"},
                }
            ],
            "payer": {"email_address": "buyer@example.test"},
        },
    )
    response = api_client.post(
        "/api/webhooks/paypal", json=payload, headers=SIGNATURE_HEADERS
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted", "duplicate": False}
    stored = db_session.scalar(select(WebhookEvent))
    assert stored is not None
    assert stored.verification_status == "SUCCESS"
    assert stored.processing_status == "PROCESSED"
    assert stored.occurred_at is not None and stored.occurred_at.tzinfo is not None
    assert stored.received_at.tzinfo is not None
    assert "payer" not in stored.raw_payload["resource"]
    assert (
        "email_address"
        not in stored.raw_payload["resource"]["purchase_units"][0]["payee"]
    )


def test_paypal_signature_is_the_webhook_posts_authentication(api_client, monkeypatch):
    verifier = SignatureClient()
    monkeypatch.setattr(webhook_routes, "PayPalClient", lambda: verifier)

    response = api_client.post(
        "/api/webhooks/paypal",
        json=_event("EVENT-WEBHOOK-AUTH", "UNSUPPORTED.EVENT"),
        headers={**SIGNATURE_HEADERS, "Authorization": ""},
    )

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert verifier.calls == 1


def test_invalid_signature_is_rejected_without_persistence(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    verifier = SignatureClient(valid=False)
    monkeypatch.setattr(webhook_routes, "PayPalClient", lambda: verifier)
    response = api_client.post(
        "/api/webhooks/paypal",
        json=_event("EVENT-1", "CHECKOUT.ORDER.APPROVED"),
        headers=SIGNATURE_HEADERS,
    )
    assert response.status_code == 400
    assert db_session.scalar(select(func.count()).select_from(WebhookEvent)) == 0


def test_missing_signature_headers_are_rejected_without_verification(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    verifier = SignatureClient()
    monkeypatch.setattr(webhook_routes, "PayPalClient", lambda: verifier)
    response = api_client.post(
        "/api/webhooks/paypal",
        json=_event("EVENT-1", "CHECKOUT.ORDER.APPROVED"),
    )
    assert response.status_code == 400
    assert verifier.calls == 0


def test_malformed_webhook_payload_is_rejected(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    verifier = SignatureClient()
    monkeypatch.setattr(webhook_routes, "PayPalClient", lambda: verifier)
    response = api_client.post(
        "/api/webhooks/paypal",
        content=b'{"id":',
        headers={"content-type": "application/json", **SIGNATURE_HEADERS},
    )
    assert response.status_code == 400
    assert verifier.calls == 0


def test_duplicate_delivery_is_acknowledged_without_second_processing(
    api_client: TestClient,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    verifier = SignatureClient()
    monkeypatch.setattr(webhook_routes, "PayPalClient", lambda: verifier)
    payload = _event("EVENT-DUP", "UNKNOWN.EVENT")
    first = api_client.post(
        "/api/webhooks/paypal", json=payload, headers=SIGNATURE_HEADERS
    )
    second = api_client.post(
        "/api/webhooks/paypal", json=payload, headers=SIGNATURE_HEADERS
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate", "duplicate": True}
    assert db_session.scalar(select(func.count()).select_from(WebhookEvent)) == 1
    assert verifier.calls == 2


@pytest.mark.parametrize(
    ("event_type", "expected_status"),
    [
        ("PAYMENT.CAPTURE.COMPLETED", "COMPLETED"),
        ("PAYMENT.CAPTURE.DENIED", "DENIED"),
    ],
)
def test_capture_events_persist_decimal_amounts(
    event_type: str,
    expected_status: str,
    db_session: Session,
):
    result = ingest_verified_event(
        db_session,
        _capture_event("EVENT-" + expected_status, event_type),
        paypal_client=(AuthoritativeOrderClient()),
        received_at=datetime(2026, 11, 11, tzinfo=timezone.utc),
    )
    assert result
    capture = db_session.scalar(select(PaymentCapture))
    assert capture is not None
    assert capture.status == expected_status
    assert capture.amount == Decimal("25.50")
    assert capture.currency == "USD"
    assert capture.paypal_created_at is not None
    assert capture.paypal_created_at.tzinfo is not None
    assert capture.updated_at.tzinfo is not None
    assert capture.paypal_order_id == "ORDER-1"


def test_late_pending_event_does_not_downgrade_completed_capture(
    db_session: Session,
):
    paypal = AuthoritativeOrderClient()
    ingest_verified_event(
        db_session,
        _capture_event("EVENT-COMPLETE", "PAYMENT.CAPTURE.COMPLETED"),
        paypal_client=paypal,
    )
    ingest_verified_event(
        db_session,
        _capture_event(
            "EVENT-PENDING",
            "PAYMENT.CAPTURE.PENDING",
            create_time="2026-11-10T00:00:00Z",
        ),
        paypal_client=paypal,
    )
    capture = db_session.scalar(select(PaymentCapture))
    assert capture is not None
    assert capture.status == "COMPLETED"
    assert capture.paypal_updated_at == datetime(2026, 11, 11, tzinfo=timezone.utc)


def test_completed_webhook_does_not_override_authoritative_pending_status(
    db_session: Session,
):
    ingest_verified_event(
        db_session,
        _capture_event("EVENT-CLAIMED-COMPLETE", "PAYMENT.CAPTURE.COMPLETED"),
        paypal_client=PendingAuthoritativeOrderClient(),
    )
    capture = db_session.scalar(select(PaymentCapture))
    assert capture is not None
    assert capture.status == "PENDING"


def test_refund_event_updates_refunded_total_without_float_conversion(
    db_session: Session,
):
    paypal = AuthoritativeOrderClient()
    ingest_verified_event(
        db_session,
        _capture_event("EVENT-COMPLETE", "PAYMENT.CAPTURE.COMPLETED"),
        paypal_client=paypal,
    )
    refund_event = _event(
        "EVENT-REFUND",
        "PAYMENT.CAPTURE.REFUNDED",
        resource={
            "id": "REFUND-1",
            "amount": {"value": "25.50", "currency_code": "USD"},
            "supplementary_data": {
                "related_ids": {
                    "order_id": "ORDER-1",
                    "capture_id": "CAPTURE-1",
                }
            },
        },
    )
    ingest_verified_event(db_session, refund_event, paypal_client=paypal)
    capture = db_session.scalar(select(PaymentCapture))
    assert capture is not None
    assert capture.status == "REFUNDED"
    assert capture.refunded_amount == Decimal("25.50")


def test_duplicate_paypal_event_id_is_unique(db_session: Session):
    paypal = PayPalClient(settings=Settings(_env_file=None))
    event = _event("EVENT-UNIQUE", "UNKNOWN.EVENT")
    assert ingest_verified_event(db_session, event, paypal_client=paypal)
    assert not ingest_verified_event(db_session, event, paypal_client=paypal)
    assert db_session.scalar(select(func.count()).select_from(WebhookEvent)) == 1


def test_event_failure_rolls_back_event_and_transaction(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    def fail(session: Session, **options):
        assert session is db_session
        assert "paypal_capture_id" in options
        raise SQLAlchemyError("database write failed")

    monkeypatch.setattr(paypal_webhooks, "upsert_capture", fail)
    with pytest.raises(SQLAlchemyError):
        ingest_verified_event(
            db_session,
            _capture_event("EVENT-ROLLBACK", "PAYMENT.CAPTURE.COMPLETED"),
            paypal_client=AuthoritativeOrderClient(),
        )
    db_session.rollback()
    assert db_session.scalar(select(func.count()).select_from(WebhookEvent)) == 0
    assert db_session.scalar(select(func.count()).select_from(PaymentCapture)) == 0


def test_database_unavailable_returns_service_unavailable():
    class UnavailableSession(Session):
        def scalars(self, *args):
            assert args
            raise OperationalError("SELECT", {}, OSError("database unavailable"))

    with pytest.raises(HTTPException) as error:
        list_orders(
            limit=50,
            offset=0,
            db=UnavailableSession(),
            principal=Principal(
                subject="unit-test",
                role=Role.ADMIN,
                merchant_id=None,
            ),
        )
    assert error.value.status_code == 503


def test_event_details_api_exposes_no_payer_contact_data(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    verifier = SignatureClient()
    monkeypatch.setattr(webhook_routes, "PayPalClient", lambda: verifier)
    payload = _event(
        "EVENT-DETAIL",
        "UNKNOWN.EVENT",
        resource={
            "id": "RESOURCE-1",
            "payer": {"email_address": "private@example.test"},
        },
    )
    api_client.post("/api/webhooks/paypal", json=payload, headers=SIGNATURE_HEADERS)
    response = api_client.get("/api/webhooks/EVENT-DETAIL")
    assert response.status_code == 200
    assert "private@example.test" not in response.text


def test_webhook_verification_api_errors_remain_sanitized():
    settings = Settings(
        _env_file=None,
        PAYPAL_CLIENT_ID="client",
        PAYPAL_CLIENT_SECRET="secret",
        PAYPAL_WEBHOOK_ID="webhook-id",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/v1/oauth2/token"):
            return httpx.Response(
                200,
                json={
                    "access_token": "private-token",
                    "token_type": "Bearer",
                    "expires_in": 300,
                },
            )
        return httpx.Response(500, json={"debug_id": "sensitive-debug"})

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        paypal = PayPalClient(settings=settings, http_client=http_client)
        with pytest.raises(PayPalApiError) as error:
            paypal.verify_webhook_signature(SIGNATURE_HEADERS, {"id": "EVENT-1"})
    assert "sensitive-debug" not in str(error.value)
    assert "private-token" not in str(error.value)

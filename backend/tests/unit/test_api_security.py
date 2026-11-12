from datetime import datetime, timedelta, timezone
from decimal import Decimal
import jwt
from sqlalchemy import select

from app.core.config import Settings, get_settings
from app.main import app
from app.models import (
    InvestigationReportRecord,
    MerchantOrder,
    PaymentCapture,
    ReconciliationExceptionRecord,
    WebhookEvent,
)

_JWT_SECRET = "unit-tests-only-secret-with-32-bytes-minimum"
_NOW = datetime.now(timezone.utc)


def _token(
    role: str,
    merchant_id: str | None = None,
    *,
    expires: datetime | None = None,
    secret: str = _JWT_SECRET,
) -> str:
    claims = {
        "iss": "payrecon-tests",
        "aud": "payrecon-test-api",
        "sub": "security-test",
        "role": role,
        "iat": _NOW,
        "exp": expires or _NOW + timedelta(minutes=5),
    }
    if merchant_id is not None:
        claims["merchant_id"] = merchant_id
    return jwt.encode(claims, secret, algorithm="HS256")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_tenant_records(db_session):
    for merchant_id, suffix, amount in (
        ("merchant-a", "A", Decimal("24.50")),
        ("merchant-b", "B", Decimal("23.50")),
    ):
        order_id = f"ORDER-{suffix}"
        capture_id = f"CAPTURE-{suffix}"
        db_session.add(
            MerchantOrder(
                merchant_id=merchant_id,
                paypal_order_id=order_id,
                merchant_reference="SHARED-REFERENCE",
                invoice_id=f"INV-{suffix}",
                amount=Decimal("25.50"),
                currency="USD",
                intent="CAPTURE",
                status="COMPLETED",
                paypal_created_at=_NOW,
            )
        )
        db_session.add(
            PaymentCapture(
                paypal_order_id=order_id,
                paypal_capture_id=capture_id,
                status="COMPLETED",
                amount=amount,
                currency="USD",
                paypal_created_at=_NOW,
            )
        )
        db_session.add(
            WebhookEvent(
                paypal_event_id=f"EVENT-{suffix}",
                event_type="PAYMENT.CAPTURE.COMPLETED",
                resource_type="capture",
                resource_id=capture_id,
                occurred_at=_NOW,
                received_at=_NOW,
                verification_status="SUCCESS",
                processing_status="PROCESSED",
                raw_payload={"id": f"EVENT-{suffix}", "resource": {"id": capture_id}},
            )
        )
    db_session.add(
        ReconciliationExceptionRecord(
            case_id="recon_aaaaaaaaaaaaaaaaaaaa",
            merchant_id="merchant-b",
            exception_type="AMOUNT_MISMATCH",
            severity="HIGH",
            merchant_order_id="SHARED-REFERENCE",
            paypal_order_id="ORDER-B",
            capture_id="CAPTURE-B",
            expected_value="25.50",
            actual_value="23.50",
            evidence_identifiers=["ORDER-B", "CAPTURE-B"],
            explanation="Synthetic test discrepancy.",
            case_status="open",
            detected_at=_NOW,
            created_at=_NOW,
        )
    )
    db_session.flush()
    db_session.add(
        InvestigationReportRecord(
            report_id="b9a2c75e-6429-41b8-8ea4-c2b086839ade",
            case_id="recon_aaaaaaaaaaaaaaaaaaaa",
            investigation_status="INCONCLUSIVE",
            issue_type="AMOUNT_MISMATCH",
            severity="HIGH",
            findings=[],
            missing_evidence=[],
            conflicting_evidence=[],
            evidence_snapshot={"case_id": "recon_aaaaaaaaaaaaaaaaaaaa"},
            deterministic_analysis={"payment_state": "COMPLETED"},
            requires_human_approval=True,
            prompt_version="1.0",
            validation_errors=[],
            investigated_at=_NOW,
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    db_session.commit()


def test_missing_invalid_and_expired_credentials_are_rejected(api_client):
    missing = api_client.get("/api/orders", headers={"Authorization": ""})
    invalid = api_client.get("/api/orders", headers=_auth("not-a-jwt"))
    expired = api_client.get(
        "/api/orders",
        headers=_auth(_token("admin", expires=_NOW - timedelta(seconds=1))),
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert expired.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"


def test_all_sensitive_read_routes_require_a_bearer_token(api_client):
    protected_paths = (
        "/api/orders",
        "/api/payments",
        "/api/webhooks",
        "/api/reconciliation",
        "/api/lineage",
        "/api/paypal/orders/ORDER-1",
        "/api/investigations/recon_aaaaaaaaaaaaaaaaaaaa/validate",
        "/api/investigations/recon_aaaaaaaaaaaaaaaaaaaa/reports",
        "/api/investigations/reports/b9a2c75e-6429-41b8-8ea4-c2b086839ade",
    )

    responses = [
        api_client.get(path, headers={"Authorization": ""})
        for path in protected_paths[:6]
    ]
    responses.append(
        api_client.post(protected_paths[6], headers={"Authorization": ""})
    )
    responses.extend(
        api_client.get(path, headers={"Authorization": ""})
        for path in protected_paths[7:]
    )

    assert [response.status_code for response in responses] == [401] * len(
        protected_paths
    )


def test_empty_payment_and_order_lists_return_empty_arrays(api_client):
    payments = api_client.get("/api/payments")
    orders = api_client.get("/api/orders")

    assert payments.status_code == 200
    assert payments.json() == []
    assert orders.status_code == 200
    assert orders.json() == []


def test_unknown_role_and_missing_tenant_claim_are_rejected(api_client):
    unknown_role = api_client.get(
        "/api/orders", headers=_auth(_token("owner", "merchant-a"))
    )
    missing_tenant = api_client.get(
        "/api/orders", headers=_auth(_token("merchant"))
    )

    assert unknown_role.status_code == 401
    assert missing_tenant.status_code == 401


def test_authentication_fails_closed_when_signing_secret_is_not_configured(
    api_client,
):
    # Explicitly override environment-backed values so a developer's local
    # .env cannot make this fail-closed test pass or fail nondeterministically.
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None,
        AUTH_JWT_SECRET="",
        AUTH_JWT_ISSUER="payrecon-tests",
        AUTH_JWT_AUDIENCE="payrecon-test-api",
    )

    response = api_client.get("/api/orders", headers=_auth(_token("admin")))

    assert response.status_code == 503
    assert response.json()["detail"] == "API authentication is not configured."


def test_read_only_role_cannot_run_mutating_operations(api_client):
    headers = _auth(_token("read_only", "merchant-a"))

    orders = api_client.get("/api/orders", headers=headers)
    reconciliation = api_client.post("/api/reconciliation/run", headers=headers)
    paypal_create = api_client.post(
        "/api/paypal/orders",
        headers=headers,
        json={
            "amount": "1.00",
            "currency": "USD",
            "return_url": "https://merchant.example/return",
            "cancel_url": "https://merchant.example/cancel",
        },
    )

    assert orders.status_code == 200
    assert reconciliation.status_code == 403
    assert paypal_create.status_code == 403


def test_merchant_cannot_read_or_investigate_another_tenant_records(
    api_client, db_session
):
    _seed_tenant_records(db_session)
    headers = _auth(_token("merchant", "merchant-a"))

    orders = api_client.get("/api/orders", headers=headers)
    payments = api_client.get("/api/payments", headers=headers)
    webhooks = api_client.get("/api/webhooks", headers=headers)
    foreign_order = api_client.get("/api/orders/ORDER-B", headers=headers)
    foreign_payment = api_client.get("/api/payments/CAPTURE-B", headers=headers)
    foreign_event = api_client.get("/api/webhooks/EVENT-B", headers=headers)
    foreign_case_run = api_client.post(
        "/api/investigations/recon_aaaaaaaaaaaaaaaaaaaa/run",
        headers=headers,
    )
    foreign_case_history = api_client.get(
        "/api/investigations/recon_aaaaaaaaaaaaaaaaaaaa/reports",
        headers=headers,
    )
    foreign_report = api_client.get(
        "/api/investigations/reports/b9a2c75e-6429-41b8-8ea4-c2b086839ade",
        headers=headers,
    )
    reconciliation = api_client.post("/api/reconciliation/run", headers=headers)

    assert orders.status_code == 200
    assert [item["order_id"] for item in orders.json()] == ["ORDER-A"]
    assert payments.status_code == 200
    assert [item["payment_id"] for item in payments.json()] == ["CAPTURE-A"]
    assert webhooks.status_code == 200
    assert [item["event_id"] for item in webhooks.json()] == ["EVENT-A"]
    assert foreign_order.status_code == 404
    assert foreign_payment.status_code == 404
    assert foreign_event.status_code == 404
    assert foreign_case_run.status_code == 404
    assert foreign_case_history.status_code == 404
    assert foreign_report.status_code == 404
    assert reconciliation.status_code == 200
    assert reconciliation.json()["order_count"] == 1
    assert reconciliation.json()["exception_count"] == 1
    created_case = db_session.scalar(
        select(ReconciliationExceptionRecord).where(
            ReconciliationExceptionRecord.paypal_order_id == "ORDER-A"
        )
    )
    assert created_case is not None
    assert created_case.merchant_id == "merchant-a"

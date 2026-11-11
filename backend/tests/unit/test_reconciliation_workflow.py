from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models import MerchantOrder, PaymentCapture, ReconciliationExceptionRecord
from app.services.reconciliation_workflow import run_persisted_reconciliation


NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def _add_order(
    session,
    *,
    order_id: str,
    merchant_reference: str,
    amount: Decimal,
    capture_amount: Decimal,
) -> None:
    session.add(
        MerchantOrder(
            paypal_order_id=order_id,
            merchant_reference=merchant_reference,
            amount=amount,
            currency="USD",
            status="COMPLETED",
            paypal_created_at=NOW - timedelta(hours=1),
        )
    )
    session.add(
        PaymentCapture(
            paypal_order_id=order_id,
            paypal_capture_id=f"CAP-{order_id}",
            status="COMPLETED",
            amount=capture_amount,
            currency="USD",
            paypal_created_at=NOW - timedelta(minutes=50),
        )
    )
    session.commit()


def test_completed_matching_payment_creates_no_exception_or_case(db_session):
    _add_order(
        db_session,
        order_id="ORDER-NORMAL",
        merchant_reference="MERCHANT-NORMAL",
        amount=Decimal("25.50"),
        capture_amount=Decimal("25.50"),
    )

    result = run_persisted_reconciliation(db_session)

    assert result.summary.exception_count == 0
    assert db_session.query(ReconciliationExceptionRecord).count() == 0


def test_genuine_amount_mismatch_is_persisted_with_all_available_links(db_session):
    _add_order(
        db_session,
        order_id="ORDER-MISMATCH",
        merchant_reference="MERCHANT-MISMATCH",
        amount=Decimal("25.50"),
        capture_amount=Decimal("24.50"),
    )

    result = run_persisted_reconciliation(db_session)

    assert result.summary.exception_count == 1
    case = db_session.query(ReconciliationExceptionRecord).one()
    assert case.exception_type == "AMOUNT_MISMATCH"
    assert case.merchant_order_id == "MERCHANT-MISMATCH"
    assert case.paypal_order_id == "ORDER-MISMATCH"
    assert case.capture_id == "CAP-ORDER-MISMATCH"
    assert Decimal(case.expected_value) == Decimal("25.50")
    assert Decimal(case.actual_value) == Decimal("24.50")
    assert set(case.evidence_identifiers) == {
        "CAP-ORDER-MISMATCH",
        "MERCHANT-MISMATCH",
        "ORDER-MISMATCH",
    }


def test_reconciliation_case_persistence_is_idempotent(db_session):
    _add_order(
        db_session,
        order_id="ORDER-IDEMPOTENT",
        merchant_reference="MERCHANT-IDEMPOTENT",
        amount=Decimal("25.50"),
        capture_amount=Decimal("24.50"),
    )

    first = run_persisted_reconciliation(db_session)
    second = run_persisted_reconciliation(db_session)

    assert first.exception_cases[0].case_id == second.exception_cases[0].case_id
    assert db_session.query(ReconciliationExceptionRecord).count() == 1


def test_reconciliation_api_runs_engine_and_returns_persisted_case_ids(
    db_session, api_client
):
    _add_order(
        db_session,
        order_id="ORDER-API",
        merchant_reference="MERCHANT-API",
        amount=Decimal("25.50"),
        capture_amount=Decimal("24.50"),
    )

    response = api_client.post("/api/reconciliation/run")

    assert response.status_code == 200
    assert response.json()["exception_count"] == 1
    case_id = response.json()["persisted_case_ids"][0]
    assert db_session.get(ReconciliationExceptionRecord, case_id) is not None


def test_read_only_completed_transaction_review_does_not_create_case(
    db_session, api_client
):
    _add_order(
        db_session,
        order_id="ORDER-REVIEW",
        merchant_reference="MERCHANT-REVIEW",
        amount=Decimal("25.50"),
        capture_amount=Decimal("25.50"),
    )

    response = api_client.post("/api/investigations/reviews/orders/ORDER-REVIEW")

    assert response.status_code == 200
    assert response.json()["verification_status"] == "MATCHED"
    assert response.json()["checks"] == {
        "amount_matches": True,
        "currency_matches": True,
        "status_matches": True,
    }
    assert db_session.query(ReconciliationExceptionRecord).count() == 0

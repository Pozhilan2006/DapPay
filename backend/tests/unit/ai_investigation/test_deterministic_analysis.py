from datetime import datetime, timedelta, timezone
from app.ai_investigation.root_cause_engine import analyze_case
from app.ai_investigation.schemas import (
    EvidenceItem,
    InvestigationEvidenceSnapshot,
    LineageSnapshot,
)
from app.models import ReconciliationExceptionRecord

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def _case(
    *,
    exception_type: str = "AMOUNT_MISMATCH",
    detected_at: datetime = NOW,
) -> ReconciliationExceptionRecord:
    return ReconciliationExceptionRecord(
        case_id="recon_0123456789abcdef0123",
        exception_type=exception_type,
        severity="HIGH",
        merchant_order_id="MERCHANT-REF-1",
        paypal_order_id="PAYPAL-ORDER-1",
        capture_id=None,
        expected_value="5000.00",
        actual_value="4500.00",
        evidence_identifiers=["MERCHANT-REF-1", "CAPTURE-1"],
        explanation="Synthetic test case.",
        case_status="open",
        detected_at=detected_at,
    )


def _evidence(
    record_type: str,
    record_id: str,
    data: dict,
    *,
    occurred_at: datetime | None = None,
    event_type: str | None = None,
    capture_id: str | None = None,
    paypal_order_id: str | None = None,
    verification_status: str | None = None,
    received_at: datetime | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        evidence_id=f"EVD-{record_id}",
        source_system="PAYPAL",
        record_type=record_type,
        source_record_id=record_id,
        data=data,
        occurred_at=occurred_at,
        received_at=received_at,
        event_type=event_type,
        capture_id=capture_id,
        paypal_order_id=paypal_order_id,
        verification_status=verification_status,
        processing_status="PROCESSED" if record_type == "WEBHOOK_EVENT" else None,
    )


def _snapshot(evidence: list[EvidenceItem]) -> InvestigationEvidenceSnapshot:
    return InvestigationEvidenceSnapshot(
        case_id="recon_0123456789abcdef0123",
        evidence=evidence,
        timeline=[],
        lineage=LineageSnapshot(),
        missing_evidence=[],
        source_availability={},
    )


def _analyze(case, evidence, *, threshold=15):
    return analyze_case(
        case,
        _snapshot(evidence),
        now=NOW,
        missing_payment_threshold=timedelta(minutes=threshold),
        webhook_delay_threshold=timedelta(minutes=1),
        merchant_update_threshold=timedelta(minutes=5),
        capture_confirmation_threshold=timedelta(minutes=15),
        accounting_delay_threshold=timedelta(minutes=60),
    )


def test_decimal_amount_difference_is_deterministic_and_evidence_linked():
    case = _case()
    case_record = _evidence(
        "EXCEPTION_CASE",
        case.case_id,
        {"expected_value": "5000.00", "actual_value": "4500.00"},
    )

    analysis = _analyze(case, [case_record])

    assert analysis.payment_state == "UNKNOWN"
    assert {
        "check": "RECONCILIATION_EXPECTED_VS_ACTUAL",
        "expected": "5000.00",
        "actual": "4500.00",
        "actual_minus_expected": "-500.00",
        "evidence_id": case_record.evidence_id,
    } in analysis.financial_checks
    assert analysis.findings[0].evidence_ids == [case_record.evidence_id]


def test_missing_payment_is_pending_until_processing_threshold_elapses():
    case = _case(
        exception_type="MISSING_PAYMENT",
        detected_at=NOW - timedelta(minutes=3),
    )
    evidence = [
        _evidence(
            "PAYPAL_ORDER",
            "PAYPAL-ORDER-1",
            {"status": "CREATED"},
            occurred_at=NOW - timedelta(minutes=3),
            paypal_order_id="PAYPAL-ORDER-1",
        )
    ]

    pending = _analyze(case, evidence, threshold=15)
    missing = _analyze(case, evidence, threshold=1)

    assert pending.payment_state == "PENDING"
    assert missing.payment_state == "MISSING"


def test_multiple_partial_captures_are_summed_without_treating_mixed_states_as_conflict():
    case = _case()
    evidence = [
        _evidence(
            "PAYPAL_ORDER",
            "PAYPAL-ORDER-1",
            {"amount": "100.00", "currency": "USD", "status": "COMPLETED"},
        ),
        _evidence(
            "PAYMENT_CAPTURE",
            "CAPTURE-1",
            {"amount": "40.00", "currency": "USD", "status": "COMPLETED"},
        ),
        _evidence(
            "PAYMENT_CAPTURE",
            "CAPTURE-2",
            {"amount": "60.00", "currency": "USD", "status": "PENDING"},
        ),
    ]

    analysis = _analyze(case, evidence)

    assert analysis.payment_state == "PENDING"
    assert {
        "check": "CAPTURE_TOTAL_BY_CURRENCY",
        "currency": "USD",
        "captured_total": "100.00",
        "capture_count": 2,
    } in analysis.financial_checks
    assert not analysis.conflicting_evidence


def test_latest_verified_capture_event_conflict_is_explicitly_evidenced():
    case = _case()
    capture = _evidence(
        "PAYMENT_CAPTURE",
        "CAPTURE-1",
        {"amount": "25.50", "currency": "USD", "status": "PENDING"},
        capture_id="CAPTURE-1",
    )
    old_event = _evidence(
        "WEBHOOK_EVENT",
        "EVENT-OLD",
        {},
        event_type="PAYMENT.CAPTURE.PENDING",
        capture_id="CAPTURE-1",
        verification_status="SUCCESS",
        occurred_at=NOW - timedelta(minutes=4),
        received_at=NOW - timedelta(minutes=1),
    )
    latest = _evidence(
        "WEBHOOK_EVENT",
        "EVENT-LATEST",
        {},
        event_type="PAYMENT.CAPTURE.COMPLETED",
        capture_id="CAPTURE-1",
        verification_status="SUCCESS",
        occurred_at=NOW - timedelta(minutes=2),
        received_at=NOW - timedelta(minutes=5),
    )

    analysis = _analyze(case, [capture, old_event, latest])

    assert capture.evidence_id in analysis.conflicting_evidence
    assert latest.evidence_id in analysis.conflicting_evidence
    conflict = next(
        item
        for item in analysis.findings
        if item.finding_type == "DETERMINISTIC_CONCLUSION"
        and "conflicts with" in item.claim
    )
    assert set(conflict.evidence_ids) == {
        capture.evidence_id,
        latest.evidence_id,
    }


def test_float_financial_values_are_not_used_as_decimal_inputs():
    case = _case()
    evidence = [
        _evidence(
            "PAYMENT_CAPTURE",
            "CAPTURE-1",
            {"amount": 1.1, "currency": "USD", "status": "COMPLETED"},
        )
    ]

    analysis = _analyze(case, evidence)

    assert not any(
        item.get("check") == "CAPTURE_TOTAL_BY_CURRENCY"
        for item in analysis.financial_checks
    )


def test_missing_order_timestamp_does_not_invent_a_missing_payment_age():
    case = _case(exception_type="MISSING_PAYMENT")
    evidence = [
        _evidence(
            "PAYPAL_ORDER",
            "PAYPAL-ORDER-1",
            {"status": "CREATED"},
            paypal_order_id="PAYPAL-ORDER-1",
        )
    ]

    assert _analyze(case, evidence, threshold=0).payment_state == "UNKNOWN"


def test_finding_ids_stay_within_schema_limit_for_long_provider_ids():
    case = _case()
    long_id = "P" * 128
    evidence = [
        _evidence(
            "PAYMENT_CAPTURE",
            long_id,
            {"amount": "1.00", "currency": "USD", "status": "COMPLETED"},
            capture_id=long_id,
        )
    ]

    analysis = _analyze(case, evidence)

    assert analysis.findings
    assert all(len(finding.finding_id) <= 64 for finding in analysis.findings)


def test_capture_with_missing_currency_does_not_break_currency_aggregation():
    case = _case()
    evidence = [
        _evidence(
            "PAYMENT_CAPTURE",
            "CAPTURE-UNKNOWN-CURRENCY",
            {"amount": "1.00", "currency": None, "status": "COMPLETED"},
        ),
        _evidence(
            "PAYMENT_CAPTURE",
            "CAPTURE-USD",
            {"amount": "2.00", "currency": "USD", "status": "COMPLETED"},
        ),
    ]

    analysis = _analyze(case, evidence)

    assert {
        "check": "CAPTURE_TOTAL_BY_CURRENCY",
        "currency": "USD",
        "captured_total": "2.00",
        "capture_count": 1,
    } in analysis.financial_checks

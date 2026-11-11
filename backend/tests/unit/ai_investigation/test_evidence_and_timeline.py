from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.ai_investigation.evidence_collector import collect_investigation_evidence
from app.ai_investigation.schemas import EvidenceItem
from app.ai_investigation.timeline_builder import build_payment_timeline
from app.models import (
    MerchantOrder,
    PaymentCapture,
    ReconciliationExceptionRecord,
    WebhookEvent,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
CASE_ID = "recon_0123456789abcdef0123"


def _case() -> ReconciliationExceptionRecord:
    return ReconciliationExceptionRecord(
        case_id=CASE_ID,
        exception_type="AMOUNT_MISMATCH",
        severity="HIGH",
        merchant_order_id="MERCHANT-REF-1",
        paypal_order_id="PAYPAL-ORDER-1",
        capture_id="CAPTURE-1",
        expected_value="25.50",
        actual_value="20.00",
        evidence_identifiers=["MERCHANT-REF-1", "CAPTURE-1"],
        explanation="Synthetic amount mismatch.",
        case_status="open",
        detected_at=NOW,
        created_at=NOW,
    )


def test_collector_retrieves_only_explicitly_related_records_and_redacts_data(
    db_session,
):
    db_session.add(_case())
    db_session.add(
        MerchantOrder(
            paypal_order_id="PAYPAL-ORDER-1",
            merchant_reference="MERCHANT-REF-1",
            invoice_id="INV-1",
            amount=Decimal("25.50"),
            currency="USD",
            status="COMPLETED",
            paypal_created_at=NOW - timedelta(minutes=10),
            paypal_updated_at=NOW - timedelta(minutes=5),
        )
    )
    db_session.add(
        PaymentCapture(
            paypal_capture_id="CAPTURE-1",
            paypal_order_id="PAYPAL-ORDER-1",
            status="COMPLETED",
            amount=Decimal("20.00"),
            refunded_amount=Decimal("2.00"),
            currency="USD",
            paypal_created_at=NOW - timedelta(minutes=3),
            paypal_updated_at=NOW - timedelta(minutes=2),
        )
    )
    db_session.add(
        WebhookEvent(
            paypal_event_id="EVENT-1",
            event_type="PAYMENT.CAPTURE.COMPLETED",
            resource_type="capture",
            resource_id="CAPTURE-1",
            occurred_at=NOW - timedelta(minutes=3),
            received_at=NOW - timedelta(minutes=2),
            verification_status="SUCCESS",
            processing_status="PROCESSED",
            raw_payload={
                "id": "EVENT-1",
                "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {
                    "id": "CAPTURE-1",
                    "status": "COMPLETED",
                    "amount": {"value": "20.00", "currency_code": "USD"},
                    "payer": {"email_address": "private@example.test"},
                },
            },
        )
    )
    db_session.commit()

    snapshot = collect_investigation_evidence(
        db_session, db_session.get(ReconciliationExceptionRecord, CASE_ID)
    )
    again = collect_investigation_evidence(
        db_session, db_session.get(ReconciliationExceptionRecord, CASE_ID)
    )

    assert [item.evidence_id for item in snapshot.evidence] == [
        item.evidence_id for item in again.evidence
    ]
    assert {item.record_type for item in snapshot.evidence} == {
        "EXCEPTION_CASE",
        "PAYPAL_ORDER",
        "PAYMENT_CAPTURE",
        "WEBHOOK_EVENT",
    }
    assert "private@example.test" not in snapshot.model_dump_json()
    assert snapshot.source_availability["merchant_source_orders"] == "UNAVAILABLE"
    assert snapshot.source_availability["accounting_entries"] == "UNAVAILABLE"
    assert any(
        edge["relationship_type"] == "CAPTURED_AS"
        for edge in snapshot.lineage.edges
    )
    assert any(
        item["relationship_type"] == "CREATED_FROM"
        for item in snapshot.lineage.missing_relationships
    )


def test_timeline_orders_by_occurrence_and_marks_receipt_time_fallback():
    occurred = EvidenceItem(
        evidence_id="EVD-1",
        source_system="PAYPAL",
        record_type="WEBHOOK_EVENT",
        source_record_id="EVENT-1",
        event_type="PAYMENT.CAPTURE.COMPLETED",
        occurred_at=NOW - timedelta(minutes=1),
        received_at=NOW - timedelta(minutes=4),
    )
    fallback = EvidenceItem(
        evidence_id="EVD-2",
        source_system="PAYPAL",
        record_type="WEBHOOK_EVENT",
        source_record_id="EVENT-2",
        event_type="PAYMENT.CAPTURE.PENDING",
        received_at=NOW - timedelta(minutes=2),
    )

    timeline = build_payment_timeline([occurred, fallback])

    assert [item.event_id for item in timeline] == ["EVENT-2", "EVENT-1"]
    assert timeline[0].ordering_source == "RECEIVED_AT"
    assert timeline[0].occurred_at is None
    assert timeline[0].received_at == NOW - timedelta(minutes=2)

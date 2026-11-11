from __future__ import annotations

from datetime import datetime, timezone

from app.ai_investigation.schemas import EvidenceItem, TimelineItem


def build_payment_timeline(
    evidence: list[EvidenceItem],
) -> list[TimelineItem]:
    items = [
        TimelineItem(
            event_id=item.source_record_id,
            evidence_id=item.evidence_id,
            event_type=item.event_type or item.record_type,
            source_system=item.source_system,
            related_order_id=item.related_order_id,
            paypal_order_id=item.paypal_order_id,
            capture_id=item.capture_id,
            refund_id=item.refund_id,
            occurred_at=item.occurred_at,
            received_at=item.received_at,
            processing_status=item.processing_status,
            verification_status=item.verification_status,
            related_record_ids=[
                value
                for value in (
                    item.related_order_id,
                    item.paypal_order_id,
                    item.capture_id,
                    item.refund_id,
                )
                if value is not None
            ],
            ordering_source=(
                "OCCURRED_AT"
                if item.occurred_at is not None
                else "RECEIVED_AT"
                if item.received_at is not None
                else "UNAVAILABLE"
            ),
        )
        for item in evidence
    ]
    return sorted(
        items,
        key=lambda item: (
            item.occurred_at
            or item.received_at
            or datetime.max.replace(tzinfo=timezone.utc),
            item.event_id,
            item.evidence_id,
        ),
    )

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_investigation.schemas import (
    EvidenceItem,
    InvestigationEvidenceSnapshot,
    LineageSnapshot,
)
from app.lineage.graph_builder import LineageGraphBuilder
from app.models import (
    MerchantOrder,
    PaymentCapture,
    ReconciliationExceptionRecord,
    WebhookEvent,
)
from app.services.payment_persistence import sanitize_event_payload

_MAX_RELATED_RECORDS = 200
_EVENT_RESOURCE_FIELDS = frozenset(
    {
        "id",
        "status",
        "amount",
        "currency",
        "invoice_id",
        "custom_id",
        "reference_id",
        "update_time",
        "create_time",
    }
)


def collect_investigation_evidence(
    session: Session, case: ReconciliationExceptionRecord
) -> InvestigationEvidenceSnapshot:
    """Collect only records reachable by explicit IDs from a persisted case."""
    evidence: list[EvidenceItem] = []
    evidence.append(
        _evidence(
            source_system="RECONCILIATION",
            record_type="EXCEPTION_CASE",
            source_record_id=case.case_id,
            related_order_id=case.merchant_order_id,
            paypal_order_id=case.paypal_order_id,
            capture_id=case.capture_id,
            data={
                "issue_type": case.exception_type,
                "severity": case.severity,
                "status": case.case_status,
                "expected_value": _safe_case_value(case.expected_value),
                "actual_value": _safe_case_value(case.actual_value),
                "evidence_identifiers": case.evidence_identifiers,
            },
            occurred_at=case.detected_at,
        )
    )

    orders_by_id: dict[str, MerchantOrder] = {}
    if case.paypal_order_id:
        order_query = select(MerchantOrder).where(
            MerchantOrder.paypal_order_id == case.paypal_order_id
        )
        if case.merchant_id is not None:
            order_query = order_query.where(
                MerchantOrder.merchant_id == case.merchant_id
            )
        order = session.scalar(order_query)
        if order is not None:
            orders_by_id[order.paypal_order_id] = order
    if case.merchant_order_id:
        order_query = (
            select(MerchantOrder)
            .where(MerchantOrder.merchant_reference == case.merchant_order_id)
            .order_by(MerchantOrder.paypal_order_id)
            .limit(_MAX_RELATED_RECORDS + 1)
        )
        if case.merchant_id is not None:
            order_query = order_query.where(
                MerchantOrder.merchant_id == case.merchant_id
            )
        matching_orders = session.scalars(order_query).all()
        for order in matching_orders:
            orders_by_id[order.paypal_order_id] = order

    captures_by_id: dict[str, PaymentCapture] = {}
    if orders_by_id:
        captures = session.scalars(
            select(PaymentCapture)
            .where(PaymentCapture.paypal_order_id.in_(tuple(orders_by_id)))
            .order_by(PaymentCapture.paypal_capture_id)
            .limit(_MAX_RELATED_RECORDS + 1)
        ).all()
        captures_by_id.update(
            {capture.paypal_capture_id: capture for capture in captures}
        )
    if case.capture_id:
        capture_query = select(PaymentCapture).where(
            PaymentCapture.paypal_capture_id == case.capture_id
        )
        if case.merchant_id is not None:
            capture_query = capture_query.join(
                MerchantOrder,
                MerchantOrder.paypal_order_id == PaymentCapture.paypal_order_id,
            ).where(MerchantOrder.merchant_id == case.merchant_id)
        capture = session.scalar(capture_query)
        if capture is not None:
            captures_by_id[capture.paypal_capture_id] = capture
            order_query = select(MerchantOrder).where(
                MerchantOrder.paypal_order_id == capture.paypal_order_id
            )
            if case.merchant_id is not None:
                order_query = order_query.where(
                    MerchantOrder.merchant_id == case.merchant_id
                )
            order = session.scalar(order_query)
            if order is not None:
                orders_by_id[order.paypal_order_id] = order

    related_resource_ids = {
        *orders_by_id.keys(),
        *captures_by_id.keys(),
    }
    webhook_rows = (
        session.scalars(
            select(WebhookEvent)
            .where(WebhookEvent.resource_id.in_(related_resource_ids))
            .order_by(WebhookEvent.occurred_at, WebhookEvent.paypal_event_id)
            .limit(_MAX_RELATED_RECORDS + 1)
        ).all()
        if related_resource_ids
        else []
    )
    truncated = (
        len(orders_by_id) > _MAX_RELATED_RECORDS
        or len(captures_by_id) > _MAX_RELATED_RECORDS
        or len(webhook_rows) > _MAX_RELATED_RECORDS
    )
    if len(orders_by_id) > _MAX_RELATED_RECORDS:
        orders_by_id = _limited_mapping(orders_by_id, preferred_id=case.paypal_order_id)
    if len(captures_by_id) > _MAX_RELATED_RECORDS:
        captures_by_id = _limited_mapping(captures_by_id, preferred_id=case.capture_id)
    webhook_rows = webhook_rows[:_MAX_RELATED_RECORDS]
    for order in sorted(orders_by_id.values(), key=lambda item: item.paypal_order_id):
        evidence.append(
            _evidence(
                source_system="PAYPAL",
                record_type="PAYPAL_ORDER",
                source_record_id=order.paypal_order_id,
                related_order_id=case.merchant_order_id,
                paypal_order_id=order.paypal_order_id,
                occurred_at=order.paypal_created_at,
                data={
                    "merchant_reference": order.merchant_reference,
                    "invoice_id": order.invoice_id,
                    "amount": _money(order.amount),
                    "currency": order.currency,
                    "intent": order.intent,
                    "status": order.status,
                    "created_at": order.paypal_created_at,
                    "updated_at": order.paypal_updated_at,
                },
            )
        )
    for capture in sorted(
        captures_by_id.values(), key=lambda item: item.paypal_capture_id
    ):
        evidence.append(
            _evidence(
                source_system="PAYPAL",
                record_type="PAYMENT_CAPTURE",
                source_record_id=capture.paypal_capture_id,
                related_order_id=case.merchant_order_id,
                paypal_order_id=capture.paypal_order_id,
                capture_id=capture.paypal_capture_id,
                occurred_at=capture.paypal_created_at,
                data={
                    "status": capture.status,
                    "amount": _money(capture.amount),
                    "refunded_amount": _money(capture.refunded_amount),
                    "currency": capture.currency,
                    "created_at": capture.paypal_created_at,
                    "updated_at": capture.paypal_updated_at,
                },
            )
        )

    for event in webhook_rows:
        item = _evidence(
            source_system="PAYPAL",
            record_type="WEBHOOK_EVENT",
            source_record_id=event.paypal_event_id,
            related_order_id=case.merchant_order_id,
            paypal_order_id=(
                event.resource_id if event.resource_id in orders_by_id else None
            ),
            capture_id=(
                event.resource_id if event.resource_id in captures_by_id else None
            ),
            event_type=event.event_type,
            occurred_at=event.occurred_at,
            received_at=event.received_at,
            processing_status=event.processing_status,
            verification_status=event.verification_status,
            data={
                "resource_type": event.resource_type,
                "resource_id": event.resource_id,
                "resource": _safe_event_resource(event.raw_payload),
            },
        )
        evidence.append(item)

    payment_dtos = _payment_dtos(case, captures_by_id)
    webhook_dtos = _webhook_dtos(webhook_rows)
    graph = LineageGraphBuilder().build(
        paypal_payments=payment_dtos,
        webhook_events=webhook_dtos,
    )
    nodes = [_json_safe(attributes) for _, attributes in graph.nodes]
    edges = [
        {
            "source": source,
            "target": target,
            **_json_safe(attributes),
        }
        for source, target, attributes in graph.edges
    ]
    connected = {
        node_id for source, target, _ in graph.edges for node_id in (source, target)
    }
    disconnected = sorted(
        node_id for node_id, _ in graph.nodes if node_id not in connected
    )
    missing_relationships = [
        {
            "relationship_type": item.relationship_type.value,
            "endpoint_node_type": (
                item.endpoint_node_type.value if item.endpoint_node_type else None
            ),
            "external_record_id": item.external_record_id,
            "evidence_reference": item.evidence_reference,
            "reason": item.reason,
            "candidate_node_ids": list(item.candidate_node_ids),
        }
        for item in graph.missing_relationship_endpoints
    ]
    if not orders_by_id:
        missing_relationships.append(
            {
                "relationship_type": "CREATED_FROM",
                "endpoint_node_type": "PAYPAL_ORDER",
                "external_record_id": case.paypal_order_id,
                "evidence_reference": case.case_id,
                "reason": "No related persisted PayPal order was found.",
                "candidate_node_ids": [],
            }
        )
    if orders_by_id and not captures_by_id:
        missing_relationships.extend(
            {
                "relationship_type": "CAPTURED_AS",
                "endpoint_node_type": "PAYMENT_CAPTURE",
                "external_record_id": None,
                "evidence_reference": order_id,
                "reason": "No related persisted capture was found.",
                "candidate_node_ids": [],
            }
            for order_id in sorted(orders_by_id)
        )
    availability = {
        "exception_case": "AVAILABLE",
        "paypal_orders": "AVAILABLE",
        "payment_captures": "AVAILABLE",
        "webhook_events": "AVAILABLE",
        "webhook_delivery_attempts": "NOT_PERSISTED",
        "merchant_source_orders": "UNAVAILABLE",
        "refund_records": "UNAVAILABLE",
        "fulfillment_records": "UNAVAILABLE",
        "accounting_entries": "UNAVAILABLE",
        "merchant_status_updates": "UNAVAILABLE",
    }
    missing = []
    if not orders_by_id:
        missing.append("Related PayPal order was not found in persistence.")
    if not captures_by_id:
        missing.append("Related PayPal capture was not found in persistence.")
    if not webhook_rows:
        missing.append("No related persisted webhook events were found.")
    missing.append(
        "Individual duplicate webhook delivery attempts are not persisted; "
        "idempotency cannot be reconstructed from event rows alone."
    )
    if case.merchant_order_id and len(orders_by_id) > 1 and not case.paypal_order_id:
        missing.append(
            "Multiple PayPal orders share this merchant reference; association "
            "is ambiguous."
        )
    if truncated:
        missing.append(
            "Related source records exceeded the investigation collection limit; "
            "the evidence snapshot may be incomplete."
        )
    missing.extend(
        f"{source.replace('_', ' ').capitalize()} source is not implemented."
        for source in (
            "merchant_source_orders",
            "refund_records",
            "fulfillment_records",
            "accounting_entries",
            "merchant_status_updates",
        )
    )
    return InvestigationEvidenceSnapshot(
        case_id=case.case_id,
        evidence=evidence,
        lineage=LineageSnapshot(
            nodes=nodes,
            edges=edges,
            missing_relationships=missing_relationships,
            disconnected_node_ids=disconnected,
            source_availability=availability,
        ),
        source_availability=availability,
        missing_evidence=missing,
    )


def _evidence(
    *,
    source_system: str,
    record_type: str,
    source_record_id: str,
    data: dict[str, Any],
    related_order_id: str | None = None,
    paypal_order_id: str | None = None,
    capture_id: str | None = None,
    refund_id: str | None = None,
    event_type: str | None = None,
    occurred_at: Any = None,
    received_at: Any = None,
    processing_status: str | None = None,
    verification_status: str | None = None,
) -> EvidenceItem:
    identity = "\0".join((source_system, record_type, source_record_id))
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
    return EvidenceItem(
        evidence_id=f"EVD-{digest}",
        source_system=source_system,
        record_type=record_type,
        source_record_id=source_record_id,
        related_order_id=related_order_id,
        paypal_order_id=paypal_order_id,
        capture_id=capture_id,
        refund_id=refund_id,
        event_type=event_type,
        occurred_at=occurred_at,
        received_at=received_at,
        processing_status=processing_status,
        verification_status=verification_status,
        data=_json_safe(data),
    )


def _safe_case_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _safe_case_value(item)
            for key, item in value.items()
            if key.lower()
            in {"amount", "currency", "status", "id", "capture_id", "order_id"}
            or re.fullmatch(r"[A-Za-z]{3}", key) is not None
        }
    if isinstance(value, float):
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.isoformat()
    if isinstance(value, (str, int, Decimal)) or value is None:
        return _money(value) if isinstance(value, Decimal) else value
    if isinstance(value, list):
        return [_safe_case_value(item) for item in value[:50]]
    return None


def _safe_event_resource(payload: dict[str, Any]) -> dict[str, Any]:
    resource = payload.get("resource")
    if not isinstance(resource, dict):
        return {}
    sanitized = sanitize_event_payload(resource)
    return {
        key: _json_safe(value)
        for key, value in sanitized.items()
        if key in _EVENT_RESOURCE_FIELDS
    }


def _payment_dtos(
    case: ReconciliationExceptionRecord,
    captures: dict[str, PaymentCapture],
) -> tuple[Any, ...]:
    from app.integration_contracts.payment_data import ProvisionalPayPalPayment

    merchant_order_id = case.merchant_order_id
    if not merchant_order_id:
        return ()
    result = []
    for capture in captures.values():
        if capture.amount is None or capture.currency is None or capture.status is None:
            continue
        result.append(
            ProvisionalPayPalPayment(
                paypal_order_id=capture.paypal_order_id,
                paypal_capture_id=capture.paypal_capture_id,
                merchant_order_id=merchant_order_id,
                actual_payment_amount=capture.amount,
                currency=capture.currency,
                capture_status=capture.status,
                capture_timestamp=capture.paypal_created_at,
            )
        )
    return tuple(result)


def _webhook_dtos(rows: list[WebhookEvent]) -> tuple[Any, ...]:
    from app.integration_contracts.payment_data import ProvisionalWebhookEvent

    result = []
    for event in rows:
        if event.resource_id is None or event.occurred_at is None:
            continue
        result.append(
            ProvisionalWebhookEvent(
                paypal_event_id=event.paypal_event_id,
                event_type=event.event_type,
                related_resource_id=event.resource_id,
                occurred_at=event.occurred_at,
                received_at=event.received_at,
                verification_status=event.verification_status,
                original_event_payload=_safe_event_resource(event.raw_payload),
            )
        )
    return tuple(result)


def _money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _limited_mapping(
    values: dict[str, Any], *, preferred_id: str | None
) -> dict[str, Any]:
    keys = sorted(values)
    if preferred_id in values:
        keys.remove(preferred_id)
        keys.insert(0, preferred_id)
    return {key: values[key] for key in keys[:_MAX_RELATED_RECORDS]}


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value

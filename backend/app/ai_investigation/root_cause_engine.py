from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai_investigation.schemas import (
    DeterministicAnalysis,
    EvidenceItem,
    InvestigationEvidenceSnapshot,
    InvestigationFinding,
)
from app.models import ReconciliationExceptionRecord

_COMPLETED = frozenset({"COMPLETED", "CAPTURED"})
_FAILED = frozenset({"DENIED", "DECLINED", "FAILED"})
_PENDING = frozenset({"PENDING", "CREATED", "APPROVED", "IN_PROGRESS"})


def analyze_case(
    case: ReconciliationExceptionRecord,
    snapshot: InvestigationEvidenceSnapshot,
    *,
    now: datetime,
    missing_payment_threshold: timedelta,
    webhook_delay_threshold: timedelta,
    merchant_update_threshold: timedelta,
    capture_confirmation_threshold: timedelta,
    accounting_delay_threshold: timedelta,
) -> DeterministicAnalysis:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Investigation time must be timezone-aware.")
    if any(
        threshold < timedelta(0)
        for threshold in (
            missing_payment_threshold,
            webhook_delay_threshold,
            merchant_update_threshold,
            capture_confirmation_threshold,
            accounting_delay_threshold,
        )
    ):
        raise ValueError("Investigation thresholds cannot be negative.")

    evidence = snapshot.evidence
    by_type: dict[str, list[EvidenceItem]] = {}
    for item in evidence:
        by_type.setdefault(item.record_type, []).append(item)
    findings: list[InvestigationFinding] = []
    case_evidence = next(
        (
            item
            for item in evidence
            if item.record_type == "EXCEPTION_CASE"
            and item.source_record_id == case.case_id
        ),
        None,
    )
    if case_evidence is not None:
        expected = case_evidence.data.get("expected_value")
        actual = case_evidence.data.get("actual_value")
        expected_amount = _decimal(expected)
        actual_amount = _decimal(actual)
        reported_difference = (
            actual_amount - expected_amount
            if expected_amount is not None and actual_amount is not None
            else None
        )
        findings.append(
            InvestigationFinding(
                finding_id="FACT-CASE",
                claim=(
                    f"Recorded exception type is {case.exception_type}."
                    + (
                        f" The recorded actual-minus-expected difference is "
                        f"{reported_difference}."
                        if reported_difference is not None
                        else ""
                    )
                ),
                finding_type="FACT",
                evidence_ids=[case_evidence.evidence_id],
                explanation=(
                    "This fact describes the persisted reconciliation case; "
                    "it does not independently establish a payment cause."
                ),
            )
        )

    orders = by_type.get("PAYPAL_ORDER", [])
    captures = by_type.get("PAYMENT_CAPTURE", [])
    webhooks = by_type.get("WEBHOOK_EVENT", [])
    for order in orders:
        findings.append(
            InvestigationFinding(
                finding_id=_finding_id("FACT-ORDER", order.source_record_id),
                claim=(
                    f"Persisted PayPal order status is "
                    f"{order.data.get('status') or 'unavailable'}."
                ),
                finding_type="FACT",
                evidence_ids=[order.evidence_id],
                explanation=(
                    "Status and amount originate from the persisted PayPal order "
                    "record, not an independent merchant order source."
                ),
            )
        )
    for capture in captures:
        findings.append(
            InvestigationFinding(
                finding_id=_finding_id("FACT-CAPTURE", capture.source_record_id),
                claim=(
                    f"Persisted PayPal capture status is "
                    f"{capture.data.get('status') or 'unavailable'}."
                ),
                finding_type="FACT",
                evidence_ids=[capture.evidence_id],
                explanation=(
                    "Status and amount originate from the persisted capture "
                    "record; they do not prove a separate merchant update."
                ),
            )
        )
    for webhook in webhooks:
        findings.append(
            InvestigationFinding(
                finding_id=_finding_id("FACT-WEBHOOK", webhook.source_record_id),
                claim=(
                    f"Persisted webhook event is {webhook.event_type} with "
                    f"verification status {webhook.verification_status} and "
                    f"processing status {webhook.processing_status}."
                ),
                finding_type="FACT",
                evidence_ids=[webhook.evidence_id],
                explanation=(
                    "The stored event record documents delivery and processing "
                    "metadata; it is not independently treated as proof of capture."
                ),
            )
        )

    totals: dict[str, Decimal] = {}
    status_values: set[str] = set()
    for capture in captures:
        amount = _decimal(capture.data.get("amount"))
        currency = capture.data.get("currency")
        if amount is not None and isinstance(currency, str) and currency.strip():
            normalized_currency = currency.strip().upper()
            totals[normalized_currency] = (
                totals.get(normalized_currency, Decimal("0")) + amount
            )
    for capture in captures:
        status_value = capture.data.get("status")
        if isinstance(status_value, str):
            status_values.add(status_value.strip().upper())

    financial_checks: list[dict[str, Any]] = []
    case_evidence = next(
        (item for item in evidence if item.record_type == "EXCEPTION_CASE"), None
    )
    if case_evidence is not None:
        expected = case_evidence.data.get("expected_value")
        actual = case_evidence.data.get("actual_value")
        expected_amount = _decimal(expected)
        actual_amount = _decimal(actual)
        if expected_amount is not None and actual_amount is not None:
            financial_checks.append(
                {
                    "check": "RECONCILIATION_EXPECTED_VS_ACTUAL",
                    "expected": str(expected_amount),
                    "actual": str(actual_amount),
                    "actual_minus_expected": str(actual_amount - expected_amount),
                    "evidence_id": case_evidence.evidence_id,
                }
            )
        if (
            isinstance(expected, str)
            and isinstance(actual, str)
            and len(expected.strip()) == 3
            and len(actual.strip()) == 3
            and expected.strip().isalpha()
            and actual.strip().isalpha()
            and expected.strip().upper() != actual.strip().upper()
        ):
            financial_checks.append(
                {
                    "check": "RECONCILIATION_CURRENCY_COMPARISON",
                    "expected_currency": expected.strip().upper(),
                    "actual_currency": actual.strip().upper(),
                    "evidence_id": case_evidence.evidence_id,
                }
            )
    for currency, total in sorted(totals.items()):
        financial_checks.append(
            {
                "check": "CAPTURE_TOTAL_BY_CURRENCY",
                "currency": currency,
                "captured_total": str(total),
                "capture_count": sum(
                    str(capture.data.get("currency") or "").upper() == currency
                    and _decimal(capture.data.get("amount")) is not None
                    for capture in captures
                ),
            }
        )
    order_amounts = {
        currency.strip().upper(): _decimal(order.data.get("amount"))
        for order in orders
        if isinstance((currency := order.data.get("currency")), str)
    }
    for currency, captured_total in totals.items():
        order_amount = order_amounts.get(currency)
        if order_amount is not None:
            financial_checks.append(
                {
                    "check": "PAYPAL_ORDER_VS_CAPTURE_TOTAL",
                    "currency": currency,
                    "order_amount": str(order_amount),
                    "captured_total": str(captured_total),
                    "difference": str(order_amount - captured_total),
                }
            )

    refunded_totals: dict[str, Decimal] = {}
    for capture in captures:
        currency = capture.data.get("currency")
        refunded = _decimal(capture.data.get("refunded_amount"))
        if isinstance(currency, str) and refunded is not None and refunded > 0:
            key = currency.strip().upper()
            refunded_totals[key] = refunded_totals.get(key, Decimal("0")) + refunded
    for currency, amount in sorted(refunded_totals.items()):
        financial_checks.append(
            {
                "check": "PERSISTED_CAPTURE_REFUNDED_TOTAL",
                "currency": currency,
                "refunded_total": str(amount),
                "limitation": "Refund-level records and IDs are not persisted.",
            }
        )

    conflicting_evidence: list[str] = []
    latest_event_by_capture: dict[str, EvidenceItem] = {}
    event_statuses = {
        "PAYMENT.CAPTURE.COMPLETED": "COMPLETED",
        "PAYMENT.CAPTURE.DENIED": "DENIED",
        "PAYMENT.CAPTURE.PENDING": "PENDING",
    }
    for webhook in webhooks:
        event_status = event_statuses.get((webhook.event_type or "").upper())
        capture_id = webhook.capture_id
        if (
            event_status is None
            or capture_id is None
            or (webhook.verification_status or "").casefold()
            not in {"success", "verified"}
        ):
            continue
        previous = latest_event_by_capture.get(capture_id)
        if previous is None or _event_order(webhook) > _event_order(previous):
            latest_event_by_capture[capture_id] = webhook
    captures_by_id = {capture.capture_id: capture for capture in captures}
    for capture_id, event in latest_event_by_capture.items():
        capture = captures_by_id.get(capture_id or "")
        event_status = event_statuses[(event.event_type or "").upper()]
        if (
            capture is not None
            and str(capture.data.get("status", "")).upper() != event_status
        ):
            conflicting_evidence.extend([capture.evidence_id, event.evidence_id])
            findings.append(
                InvestigationFinding(
                    finding_id=_finding_id("CONFLICT-CAPTURE", capture_id),
                    claim=(
                        f"Persisted capture status {capture.data.get('status')} "
                        f"conflicts with the latest verified webhook event status "
                        f"{event_status}."
                    ),
                    finding_type="DETERMINISTIC_CONCLUSION",
                    evidence_ids=[capture.evidence_id, event.evidence_id],
                    explanation=(
                        "The conflict is based on explicit capture ID and event "
                        "occurrence time; neither record is silently selected as "
                        "the authoritative winner."
                    ),
                )
            )

    approval_times: dict[str, datetime] = {}
    for webhook in webhooks:
        if (
            webhook.event_type == "CHECKOUT.ORDER.APPROVED"
            and webhook.verification_status
            and webhook.verification_status.casefold() in {"success", "verified"}
            and webhook.paypal_order_id
            and webhook.occurred_at
        ):
            existing = approval_times.get(webhook.paypal_order_id)
            if existing is None or webhook.occurred_at > existing:
                approval_times[webhook.paypal_order_id] = webhook.occurred_at
    for capture in captures:
        approval_time = approval_times.get(capture.paypal_order_id or "")
        if (
            approval_time is not None
            and capture.occurred_at is not None
            and capture.occurred_at < approval_time
        ):
            event = next(
                (
                    item
                    for item in webhooks
                    if item.paypal_order_id == capture.paypal_order_id
                    and item.event_type == "CHECKOUT.ORDER.APPROVED"
                    and item.occurred_at == approval_time
                ),
                None,
            )
            if event is not None:
                conflicting_evidence.extend(
                    [capture.evidence_id, event.evidence_id]
                )
                financial_checks.append(
                    {
                        "check": "CAPTURE_PRECEDES_APPROVAL_EVENT",
                        "capture_evidence_id": capture.evidence_id,
                        "approval_evidence_id": event.evidence_id,
                    }
                )

    for capture in captures:
        if str(capture.data.get("status", "")).upper() not in _PENDING:
            continue
        if capture.occurred_at is None:
            continue
        elapsed = now.astimezone(timezone.utc) - capture.occurred_at.astimezone(
            timezone.utc
        )
        if elapsed >= capture_confirmation_threshold:
            financial_checks.append(
                {
                    "check": "CAPTURE_CONFIRMATION_DELAY",
                    "evidence_id": capture.evidence_id,
                    "delay_seconds": int(elapsed.total_seconds()),
                    "threshold_seconds": int(
                        capture_confirmation_threshold.total_seconds()
                    ),
                    "classification": "DELAYED_NOT_FAILED",
                }
            )

    payment_state = _payment_state(
        case=case,
        captures=captures,
        orders=orders,
        status_values=status_values,
        now=now,
        missing_threshold=missing_payment_threshold,
        capture_threshold=capture_confirmation_threshold,
    )


    for webhook in webhooks:
        event_time = webhook.occurred_at
        if (
            event_time is not None
            and webhook.received_at is not None
            and webhook.received_at - event_time >= webhook_delay_threshold
        ):
            financial_checks.append(
                {
                    "check": "WEBHOOK_DELIVERY_DELAY",
                    "evidence_id": webhook.evidence_id,
                    "delay_seconds": int(
                        (webhook.received_at - event_time).total_seconds()
                    ),
                    "threshold_seconds": int(
                        webhook_delay_threshold.total_seconds()
                    ),
                }
            )

    financial_checks.extend(
        [
            {
                "check": "MERCHANT_UPDATE_SOURCE",
                "status": "UNAVAILABLE",
                "threshold_seconds": int(merchant_update_threshold.total_seconds()),
            },
            {
                "check": "ACCOUNTING_ENTRY_SOURCE",
                "status": "UNAVAILABLE",
                "threshold_seconds": int(accounting_delay_threshold.total_seconds()),
            },
        ]
    )

    missing = list(snapshot.missing_evidence)
    if case.exception_type == "STATUS_MISMATCH" and captures:
        if not any(
            item.event_type == "CHECKOUT.ORDER.APPROVED" for item in webhooks
        ):
            missing.append(
                "No persisted checkout approval event was found; approval history "
                "may be incomplete."
            )
    if case.exception_type == "STATUS_MISMATCH" and captures and not orders:
        missing.append(
            "The PayPal order status is unavailable for cross-record comparison."
        )
    if payment_state == "PENDING":
        missing.append("Payment processing window has not elapsed.")

    return DeterministicAnalysis(
        case_id=case.case_id,
        issue_type=case.exception_type,
        severity=case.severity,
        payment_state=payment_state,
        financial_checks=financial_checks,
        findings=findings,
        missing_evidence=sorted(set(missing)),
        conflicting_evidence=sorted(set(conflicting_evidence)),
    )


def _payment_state(
    *,
    case: ReconciliationExceptionRecord,
    captures: list[EvidenceItem],
    orders: list[EvidenceItem],
    status_values: set[str],
    now: datetime,
    missing_threshold: timedelta,
    capture_threshold: timedelta,
) -> str:
    if status_values:
        if status_values.issubset(_COMPLETED):
            return "COMPLETED"
        if status_values.issubset(_FAILED):
            return "FAILED"
        if status_values & _PENDING:
            return "PENDING"
        if status_values & _COMPLETED or status_values & _FAILED:
            return "UNKNOWN"
    if captures:
        return "UNKNOWN"
    if not orders:
        return "UNKNOWN"
    order_times = [item.occurred_at for item in orders if item.occurred_at]
    if not order_times:
        return "UNKNOWN"
    order_statuses = {
        str(item.data.get("status") or "").upper()
        for item in orders
        if item.data.get("status")
    }
    if order_statuses & _PENDING:
        created = min(order_times)
    else:
        return "UNKNOWN"
    elapsed = now.astimezone(timezone.utc) - created.astimezone(timezone.utc)
    threshold = (
        missing_threshold
        if case.exception_type == "MISSING_PAYMENT"
        else capture_threshold
    )
    return "MISSING" if elapsed >= threshold else "PENDING"


def _event_order(item: EvidenceItem) -> tuple[bool, datetime, str]:
    timestamp = item.occurred_at or item.received_at
    return (
        timestamp is not None,
        timestamp or datetime.min.replace(tzinfo=timezone.utc),
        item.source_record_id,
    )


def _finding_id(prefix: str, source_id: str) -> str:
    digest = hashlib.sha256(source_id.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool) or isinstance(value, float):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None

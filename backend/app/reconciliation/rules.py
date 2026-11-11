"""Deterministic reconciliation exception definitions and validation rules."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Any, Iterable, Mapping, Sequence

from app.integration_contracts.payment_data import (
    ProvisionalMerchantBusinessRecords,
    ProvisionalMerchantOrder,
    ProvisionalPayPalPayment,
    ProvisionalWebhookEvent,
)
from app.reconciliation.matcher import MatchedTransaction
from app.utils.timestamps import utcnow


class ExceptionType(StrEnum):
    MISSING_PAYMENT = "MISSING_PAYMENT"
    MISSING_ORDER = "MISSING_ORDER"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    CURRENCY_MISMATCH = "CURRENCY_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    REFUND_MISMATCH = "REFUND_MISMATCH"
    MISSING_ACCOUNTING_ENTRY = "MISSING_ACCOUNTING_ENTRY"
    DELAYED_UPDATE = "DELAYED_UPDATE"
    DUPLICATE_WEBHOOK_DELIVERY = "DUPLICATE_WEBHOOK_DELIVERY"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


SEVERITY_BY_TYPE: dict[ExceptionType, Severity] = {
    ExceptionType.MISSING_PAYMENT: Severity.HIGH,
    ExceptionType.MISSING_ORDER: Severity.MEDIUM,
    ExceptionType.AMOUNT_MISMATCH: Severity.HIGH,
    ExceptionType.CURRENCY_MISMATCH: Severity.HIGH,
    ExceptionType.STATUS_MISMATCH: Severity.MEDIUM,
    ExceptionType.REFUND_MISMATCH: Severity.HIGH,
    ExceptionType.MISSING_ACCOUNTING_ENTRY: Severity.HIGH,
    ExceptionType.DELAYED_UPDATE: Severity.LOW,
    ExceptionType.DUPLICATE_WEBHOOK_DELIVERY: Severity.LOW,
}

DEFAULT_PAID_ORDER_STATUSES = frozenset({"paid", "completed"})
DEFAULT_SUCCESSFUL_CAPTURE_STATUSES = frozenset({"completed", "captured"})
DEFAULT_DENIED_CAPTURE_STATUSES = frozenset({"denied", "declined", "failed"})


@dataclass(frozen=True)
class ExceptionCase:
    case_id: str
    exception_type: ExceptionType
    severity: Severity
    merchant_order_id: str | None
    paypal_order_id: str | None
    capture_id: str | None
    expected_value: Any
    actual_value: Any
    evidence_identifiers: tuple[str, ...]
    explanation: str
    detected_at: datetime
    status: str = "open"


def create_exception(
    exception_type: ExceptionType,
    *,
    merchant_order_id: str | None = None,
    paypal_order_id: str | None = None,
    capture_id: str | None = None,
    expected_value: Any = None,
    actual_value: Any = None,
    evidence_identifiers: Iterable[str] = (),
    explanation: str,
    detected_at: datetime | None = None,
) -> ExceptionCase:
    """Create a stable case ID from its identifying evidence and discrepancy."""
    timestamp = detected_at or utcnow()
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("detected_at must be timezone-aware")
    evidence = tuple(sorted(set(evidence_identifiers)))
    identity = {
        "type": exception_type.value,
        "merchant_order_id": merchant_order_id,
        "paypal_order_id": paypal_order_id,
        "capture_id": capture_id,
        "expected_value": _json_value(expected_value),
        "actual_value": _json_value(actual_value),
        "evidence_identifiers": evidence,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return ExceptionCase(
        case_id=f"recon_{digest}",
        exception_type=exception_type,
        severity=SEVERITY_BY_TYPE[exception_type],
        merchant_order_id=merchant_order_id,
        paypal_order_id=paypal_order_id,
        capture_id=capture_id,
        expected_value=expected_value,
        actual_value=actual_value,
        evidence_identifiers=evidence,
        explanation=explanation,
        detected_at=timestamp,
    )


def reconcile_transaction(
    transaction: MatchedTransaction,
    *,
    detected_at: datetime,
    delay_threshold: timedelta,
    paid_order_statuses: frozenset[str] = DEFAULT_PAID_ORDER_STATUSES,
    successful_capture_statuses: frozenset[str] = DEFAULT_SUCCESSFUL_CAPTURE_STATUSES,
    denied_capture_statuses: frozenset[str] = DEFAULT_DENIED_CAPTURE_STATUSES,
) -> list[ExceptionCase]:
    order = transaction.merchant_order
    payments = transaction.payments
    if order is None:
        return [
            create_exception(
                ExceptionType.MISSING_ORDER,
                merchant_order_id=payment.merchant_order_id,
                paypal_order_id=payment.paypal_order_id,
                capture_id=payment.paypal_capture_id,
                expected_value="merchant order",
                actual_value=None,
                evidence_identifiers=_payment_evidence(payment),
                explanation="PayPal payment has no merchant order with the same merchant order ID.",
                detected_at=detected_at,
            )
            for payment in payments
        ]
    if not payments:
        if (
            _status(order.order_status) not in _normalized_statuses(paid_order_statuses)
            and not _is_delayed(order.order_created_at, detected_at, delay_threshold)
        ):
            return []
        return [
            create_exception(
                ExceptionType.MISSING_PAYMENT,
                merchant_order_id=order.merchant_order_id,
                expected_value=order.expected_amount,
                actual_value=None,
                evidence_identifiers=(order.merchant_order_id,),
                explanation="Merchant order has no matching PayPal payment record; this is not a fraud determination.",
                detected_at=detected_at,
            )
        ]

    cases: list[ExceptionCase] = []
    expected_currency = _currency(order.currency)
    successful: list[ProvisionalPayPalPayment] = []
    paid_statuses = _normalized_statuses(paid_order_statuses)
    successful_statuses = _normalized_statuses(successful_capture_statuses)
    denied_statuses = _normalized_statuses(denied_capture_statuses)
    pending_statuses = frozenset({"pending", "created", "approved", "in_progress"})
    order_is_paid = _status(order.order_status) in paid_statuses

    for payment in payments:
        payment_evidence = _payment_evidence(payment)
        capture_status = _status(payment.capture_status)
        if payment.capture_timestamp is not None and not (
            order.order_created_at <= payment.capture_timestamp <= detected_at
        ):
            cases.append(
                create_exception(
                    ExceptionType.STATUS_MISMATCH,
                    merchant_order_id=order.merchant_order_id,
                    paypal_order_id=payment.paypal_order_id,
                    capture_id=payment.paypal_capture_id,
                    expected_value={
                        "not_before": order.order_created_at,
                        "not_after": detected_at,
                    },
                    actual_value=payment.capture_timestamp,
                    evidence_identifiers=payment_evidence,
                    explanation="Capture timestamp falls outside the order-creation to detection-time window.",
                    detected_at=detected_at,
                )
            )
        if capture_status in successful_statuses:
            successful.append(payment)
            if _currency(payment.currency) != expected_currency:
                cases.append(
                    create_exception(
                        ExceptionType.CURRENCY_MISMATCH,
                        merchant_order_id=order.merchant_order_id,
                        paypal_order_id=payment.paypal_order_id,
                        capture_id=payment.paypal_capture_id,
                        expected_value=expected_currency,
                        actual_value=_currency(payment.currency),
                        evidence_identifiers=payment_evidence,
                        explanation="Successful capture currency differs from the merchant order currency.",
                        detected_at=detected_at,
                    )
                )
            if payment.capture_timestamp is None and _is_delayed(
                order.order_created_at, detected_at, delay_threshold
            ):
                cases.append(
                    create_exception(
                        ExceptionType.DELAYED_UPDATE,
                        merchant_order_id=order.merchant_order_id,
                        paypal_order_id=payment.paypal_order_id,
                        capture_id=payment.paypal_capture_id,
                        expected_value="capture timestamp",
                        actual_value=None,
                        evidence_identifiers=payment_evidence,
                        explanation="A successful capture has no capture timestamp after the configured update delay.",
                        detected_at=detected_at,
                    )
                )
        elif capture_status in denied_statuses:
            if order_is_paid:
                cases.append(
                    create_exception(
                        ExceptionType.STATUS_MISMATCH,
                        merchant_order_id=order.merchant_order_id,
                        paypal_order_id=payment.paypal_order_id,
                        capture_id=payment.paypal_capture_id,
                        expected_value="successful capture for paid order",
                        actual_value=payment.capture_status,
                        evidence_identifiers=payment_evidence,
                        explanation="Merchant order is marked paid, but a related PayPal capture is denied or failed.",
                        detected_at=detected_at,
                    )
                )
            elif _is_delayed(
                order.order_created_at, detected_at, delay_threshold
            ):
                cases.append(
                    create_exception(
                        ExceptionType.MISSING_PAYMENT,
                        merchant_order_id=order.merchant_order_id,
                        paypal_order_id=payment.paypal_order_id,
                        capture_id=payment.paypal_capture_id,
                        expected_value="successful PayPal capture",
                        actual_value=payment.capture_status,
                        evidence_identifiers=payment_evidence,
                        explanation="The related PayPal capture failed and the configured payment wait threshold has elapsed.",
                        detected_at=detected_at,
                    )
                )
        elif capture_status in pending_statuses and _is_delayed(
            order.order_created_at, detected_at, delay_threshold
        ):
            cases.append(
                create_exception(
                    ExceptionType.DELAYED_UPDATE,
                    merchant_order_id=order.merchant_order_id,
                    paypal_order_id=payment.paypal_order_id,
                    capture_id=payment.paypal_capture_id,
                    expected_value="terminal capture status",
                    actual_value=payment.capture_status,
                    evidence_identifiers=payment_evidence,
                    explanation="PayPal capture remains pending after the configured payment wait threshold.",
                    detected_at=detected_at,
                )
            )
        if payment.paypal_capture_id is None:
            cases.append(
                create_exception(
                    ExceptionType.STATUS_MISMATCH,
                    merchant_order_id=order.merchant_order_id,
                    paypal_order_id=payment.paypal_order_id,
                    expected_value="PayPal capture ID",
                    actual_value=None,
                    evidence_identifiers=payment_evidence,
                    explanation="Payment record does not identify a PayPal capture.",
                    detected_at=detected_at,
                )
            )

    has_pending = any(
        _status(payment.capture_status) in pending_statuses for payment in payments
    )
    if order_is_paid and not successful and not has_pending:
        if not any(case.exception_type == ExceptionType.STATUS_MISMATCH for case in cases):
            cases.append(
                create_exception(
                    ExceptionType.STATUS_MISMATCH,
                    merchant_order_id=order.merchant_order_id,
                    paypal_order_id=payments[0].paypal_order_id,
                    expected_value="successful capture for paid order",
                    actual_value=[payment.capture_status for payment in payments],
                    evidence_identifiers=_all_payment_evidence(payments),
                    explanation="Merchant order is marked paid but no related capture has a recognized successful status.",
                    detected_at=detected_at,
                )
            )

    comparable = [
        payment
        for payment in successful
        if _currency(payment.currency) == expected_currency
    ]
    if comparable:
        actual_total = sum(
            (payment.actual_payment_amount for payment in comparable), Decimal("0")
        )
        if actual_total != order.expected_amount:
            cases.append(
                create_exception(
                    ExceptionType.AMOUNT_MISMATCH,
                    merchant_order_id=order.merchant_order_id,
                    paypal_order_id=_single_or_none(
                        payment.paypal_order_id for payment in comparable
                    ),
                    expected_value=order.expected_amount,
                    actual_value=actual_total,
                    evidence_identifiers=_all_payment_evidence(comparable)
                    + (order.merchant_order_id,),
                    explanation=(
                        "Total successful captures in the order currency differ "
                        f"from the expected order amount by "
                        f"{actual_total - order.expected_amount} {expected_currency}."
                    ),
                    detected_at=detected_at,
                )
            )
        elif (
            not order_is_paid
            and _is_delayed(order.order_created_at, detected_at, delay_threshold)
        ):
            cases.append(
                create_exception(
                    ExceptionType.STATUS_MISMATCH,
                    merchant_order_id=order.merchant_order_id,
                    paypal_order_id=_single_or_none(
                        payment.paypal_order_id for payment in comparable
                    ),
                    expected_value="paid",
                    actual_value=order.order_status,
                    evidence_identifiers=_all_payment_evidence(comparable)
                    + (order.merchant_order_id,),
                    explanation=(
                        "Successful captures cover the merchant order total, but "
                        "the merchant order has not been marked paid after the "
                        "configured update threshold."
                    ),
                    detected_at=detected_at,
                )
            )
    return cases


def evaluate_webhook_events(
    events: Sequence[ProvisionalWebhookEvent],
    *,
    detected_at: datetime,
    delay_threshold: timedelta,
) -> list[ExceptionCase]:
    grouped: dict[str, list[ProvisionalWebhookEvent]] = {}
    cases: list[ExceptionCase] = []
    for event in events:
        grouped.setdefault(event.paypal_event_id, []).append(event)
        if event.received_at - event.occurred_at >= delay_threshold:
            cases.append(
                create_exception(
                    ExceptionType.DELAYED_UPDATE,
                    paypal_order_id=None,
                    expected_value=f"receipt delay < {delay_threshold}",
                    actual_value=event.received_at - event.occurred_at,
                    evidence_identifiers=(event.paypal_event_id,),
                    explanation="Webhook receipt occurred at least the configured delay threshold after event occurrence.",
                    detected_at=detected_at,
                )
            )
    for event_id, deliveries in grouped.items():
        if len(deliveries) > 1:
            cases.append(
                create_exception(
                    ExceptionType.DUPLICATE_WEBHOOK_DELIVERY,
                    expected_value="one delivery",
                    actual_value=len(deliveries),
                    evidence_identifiers=(event_id,),
                    explanation="The same PayPal event ID appears in multiple supplied delivery records; this is not a duplicate payment finding.",
                    detected_at=detected_at,
                )
            )
    return cases


def evaluate_status_events(
    orders: Sequence[ProvisionalMerchantOrder],
    payments: Sequence[ProvisionalPayPalPayment],
    events: Sequence[ProvisionalWebhookEvent],
    *,
    detected_at: datetime,
    delay_threshold: timedelta,
    paid_order_statuses: frozenset[str] = DEFAULT_PAID_ORDER_STATUSES,
) -> list[ExceptionCase]:
    """Compare each capture's latest verified lifecycle event with merchant state."""
    event_statuses = {
        "PAYMENT.CAPTURE.PENDING": "pending",
        "PAYMENT.CAPTURE.COMPLETED": "completed",
        "PAYMENT.CAPTURE.DENIED": "denied",
    }
    orders_by_id = {order.merchant_order_id: order for order in orders}
    payments_by_capture = {
        payment.paypal_capture_id: payment
        for payment in payments
        if payment.paypal_capture_id is not None
    }
    latest_by_capture: dict[str, ProvisionalWebhookEvent] = {}
    for event in events:
        event_status = event_statuses.get(event.event_type.upper())
        if (
            event_status is None
            or event.verification_status.strip().casefold()
            not in {"success", "verified"}
            or event.occurred_at > detected_at
        ):
            continue
        current = latest_by_capture.get(event.related_resource_id)
        if current is None or (
            event.occurred_at,
            event.paypal_event_id,
        ) > (current.occurred_at, current.paypal_event_id):
            latest_by_capture[event.related_resource_id] = event

    paid_statuses = _normalized_statuses(paid_order_statuses)
    cases: list[ExceptionCase] = []
    for capture_id, event in sorted(latest_by_capture.items()):
        payment = payments_by_capture.get(capture_id)
        if payment is None:
            continue
        order = orders_by_id.get(payment.merchant_order_id)
        if order is None:
            continue
        event_status = event_statuses[event.event_type.upper()]
        merchant_is_paid = _status(order.order_status) in paid_statuses
        evidence = _payment_evidence(payment) + (event.paypal_event_id,)
        if event_status == "pending":
            if _is_delayed(order.order_created_at, detected_at, delay_threshold):
                cases.append(
                    create_exception(
                        ExceptionType.DELAYED_UPDATE,
                        merchant_order_id=order.merchant_order_id,
                        paypal_order_id=payment.paypal_order_id,
                        capture_id=capture_id,
                        expected_value="terminal PayPal capture event",
                        actual_value=event.event_type,
                        evidence_identifiers=evidence,
                        explanation="The latest verified capture event remains pending after the configured threshold.",
                        detected_at=detected_at,
                    )
                )
            continue
        if (
            (event_status == "completed") != merchant_is_paid
            and (
                event_status != "completed"
                or _is_delayed(
                    order.order_created_at, detected_at, delay_threshold
                )
            )
        ):
            expected = "paid" if event_status == "completed" else "not paid"
            cases.append(
                create_exception(
                    ExceptionType.STATUS_MISMATCH,
                    merchant_order_id=order.merchant_order_id,
                    paypal_order_id=payment.paypal_order_id,
                    capture_id=capture_id,
                    expected_value=expected,
                    actual_value=order.order_status,
                    evidence_identifiers=evidence,
                    explanation=(
                        "Latest verified PayPal capture event indicates completion, "
                        "but the merchant order is not marked paid."
                        if event_status == "completed"
                        else "Latest verified PayPal capture event indicates denial, "
                        "but the merchant order is marked paid."
                    ),
                    detected_at=detected_at,
                )
            )
    return cases


def evaluate_refunds(
    business_records: Sequence[ProvisionalMerchantBusinessRecords],
    paypal_refund_records: Sequence[Mapping[str, Any]] | None,
    *,
    detected_at: datetime,
    payment_records: Sequence[ProvisionalPayPalPayment] = (),
) -> list[ExceptionCase]:
    """Compare complete merchant and PayPal refund snapshots when both exist."""
    if paypal_refund_records is None:
        return []

    capture_to_order = {
        payment.paypal_capture_id: payment.merchant_order_id
        for payment in payment_records
        if payment.paypal_capture_id is not None
    }
    merchant_by_order = {record.merchant_order_id: record for record in business_records}
    paypal_by_order: dict[str, list[Mapping[str, Any]]] = {}
    for refund in paypal_refund_records:
        order_id = refund.get("merchant_order_id")
        capture_id = refund.get("capture_id", refund.get("paypal_capture_id"))
        if capture_id is not None:
            capture_id = str(capture_id)
            linked_order_id = capture_to_order.get(capture_id)
            if linked_order_id is None:
                raise ValueError(
                    "PayPal refund records must link to a known original capture"
                )
            if order_id is not None and str(order_id) != linked_order_id:
                raise ValueError(
                    "PayPal refund merchant order does not match its original capture"
                )
            order_id = linked_order_id
        elif order_id is not None:
            order_captures = [
                payment.paypal_capture_id
                for payment in payment_records
                if payment.merchant_order_id == str(order_id)
                and payment.paypal_capture_id is not None
            ]
            if len(order_captures) != 1:
                raise ValueError(
                    "PayPal refund records require an explicit capture ID when "
                    "the merchant order has zero or multiple captures"
                )
            capture_id = order_captures[0]
        if order_id is None:
            raise ValueError(
                "PayPal refund records must link to a merchant order or known capture"
            )
        paypal_by_order.setdefault(str(order_id), []).append(
            {**refund, "capture_id": str(capture_id)}
        )

    cases: list[ExceptionCase] = []
    for order_id in sorted(merchant_by_order):
        business_record = merchant_by_order[order_id]
        merchant_refunds = business_record.refund_records
        paypal_refunds = paypal_by_order.get(order_id, [])
        if not merchant_refunds and not paypal_refunds:
            continue
        expected = _refund_totals(merchant_refunds)
        actual = _refund_totals(paypal_refunds)
        if expected != actual:
            evidence = [order_id]
            evidence.extend(_record_identifier(refund) for refund in merchant_refunds)
            evidence.extend(_record_identifier(refund) for refund in paypal_refunds)
            evidence.extend(
                str(refund["capture_id"])
                for refund in paypal_refunds
                if refund.get("capture_id") is not None
            )
            cases.append(
                create_exception(
                    ExceptionType.REFUND_MISMATCH,
                    merchant_order_id=order_id,
                    expected_value=expected,
                    actual_value=actual,
                    evidence_identifiers=(identifier for identifier in evidence if identifier),
                    explanation="Merchant refund totals differ from the supplied PayPal refund snapshot.",
                    detected_at=detected_at,
                )
            )
        accounting_entries = business_record.accounting_entries
        for refund in paypal_refunds:
            refund_id = _record_identifier(refund)
            capture_id = str(refund["capture_id"])
            amount = _decimal_amount(refund.get("amount"))
            currency = _currency(str(refund.get("currency", "")))
            if not currency:
                raise ValueError("Refund records must include a currency code")
            accounted = any(
                _accounting_entry_matches(
                    entry,
                    refund_id=refund_id,
                    capture_id=capture_id,
                    amount=amount,
                    currency=currency,
                )
                for entry in accounting_entries
            )
            if not accounted:
                cases.append(
                    create_exception(
                        ExceptionType.MISSING_ACCOUNTING_ENTRY,
                        merchant_order_id=order_id,
                        capture_id=capture_id,
                        expected_value={
                            "refund_id": refund_id,
                            "amount": amount,
                            "currency": currency,
                        },
                        actual_value=None,
                        evidence_identifiers=(
                            identifier
                            for identifier in (order_id, capture_id, refund_id)
                            if identifier
                        ),
                        explanation="PayPal refund has no matching merchant accounting entry.",
                        detected_at=detected_at,
                    )
                )
    return cases


def _refund_totals(records: Sequence[Mapping[str, Any]]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for record in records:
        amount = _decimal_amount(record.get("amount"))
        currency = _currency(str(record.get("currency", "")))
        if not currency:
            raise ValueError("Refund records must include a currency code")
        totals[currency] = totals.get(currency, Decimal("0")) + amount
    return totals


def _decimal_amount(value: Any) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float) or value is None:
        raise ValueError(
            "Financial amounts must be Decimal, integer, or decimal string values"
        )
    try:
        amount = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"Invalid decimal financial amount: {value!r}") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError("Financial amounts must be finite and non-negative")
    return amount


def _payment_evidence(payment: ProvisionalPayPalPayment) -> tuple[str, ...]:
    identifiers = [payment.paypal_order_id, payment.merchant_order_id]
    if payment.paypal_capture_id is not None:
        identifiers.append(payment.paypal_capture_id)
    return tuple(identifiers)


def _all_payment_evidence(
    payments: Iterable[ProvisionalPayPalPayment],
) -> tuple[str, ...]:
    return tuple(
        identifier
        for payment in payments
        for identifier in _payment_evidence(payment)
    )


def _single_or_none(values: Iterable[str]) -> str | None:
    unique = set(values)
    return next(iter(unique)) if len(unique) == 1 else None


def _currency(value: str) -> str:
    return value.strip().upper()


def _status(value: str) -> str:
    return value.strip().casefold()


def _normalized_statuses(values: Iterable[str]) -> frozenset[str]:
    return frozenset(_status(value) for value in values)


def _is_delayed(created_at: datetime, now: datetime, threshold: timedelta) -> bool:
    return now - created_at >= threshold


def _record_identifier(record: Mapping[str, Any]) -> str | None:
    for key in ("refund_id", "paypal_refund_id", "id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return None


def _accounting_entry_matches(
    entry: Mapping[str, Any],
    *,
    refund_id: str | None,
    capture_id: str,
    amount: Decimal,
    currency: str,
) -> bool:
    entry_refund_id = next(
        (
            str(entry[key])
            for key in ("paypal_refund_id", "refund_id", "reference_id")
            if entry.get(key) is not None
        ),
        None,
    )
    if refund_id is not None and entry_refund_id == refund_id:
        return True
    if str(entry.get("capture_id", entry.get("paypal_capture_id", ""))) != capture_id:
        return False
    if entry.get("amount") is None or entry.get("currency") is None:
        return False
    entry_amount = _decimal_amount(entry["amount"])
    return (
        entry_amount == amount
        and _currency(str(entry.get("currency", ""))) == currency
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value

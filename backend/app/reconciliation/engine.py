"""Database-independent deterministic reconciliation orchestration."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping, Sequence

from app.integration_contracts.payment_data import (
    ProvisionalMerchantBusinessRecords,
    ProvisionalMerchantOrder,
    ProvisionalPayPalPayment,
    ProvisionalWebhookEvent,
)
from app.reconciliation.matcher import MatchedTransaction, match_records
from app.reconciliation.rules import (
    DEFAULT_DENIED_CAPTURE_STATUSES,
    DEFAULT_PAID_ORDER_STATUSES,
    DEFAULT_SUCCESSFUL_CAPTURE_STATUSES,
    ExceptionCase,
    ExceptionType,
    evaluate_refunds,
    evaluate_status_events,
    evaluate_webhook_events,
    reconcile_transaction,
)
from app.utils.timestamps import utcnow


@dataclass(frozen=True)
class ReconciliationSummary:
    order_count: int
    payment_count: int
    matched_order_count: int
    unmatched_payment_count: int
    exception_count: int
    exceptions_by_type: dict[str, int]
    exceptions_by_severity: dict[str, int]


@dataclass(frozen=True)
class ReconciliationResult:
    transactions: tuple[MatchedTransaction, ...]
    exception_cases: tuple[ExceptionCase, ...]
    summary: ReconciliationSummary

    @property
    def matched_transactions(self) -> tuple[MatchedTransaction, ...]:
        return tuple(
            transaction
            for transaction in self.transactions
            if transaction.merchant_order is not None and transaction.payments
        )


class ReconciliationEngine:
    """Reconcile snapshots supplied by callers; performs no I/O or persistence."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = utcnow,
        delay_threshold: timedelta = timedelta(minutes=15),
        paid_order_statuses: frozenset[str] = DEFAULT_PAID_ORDER_STATUSES,
        successful_capture_statuses: frozenset[str] = DEFAULT_SUCCESSFUL_CAPTURE_STATUSES,
        denied_capture_statuses: frozenset[str] = DEFAULT_DENIED_CAPTURE_STATUSES,
    ) -> None:
        if delay_threshold < timedelta(0):
            raise ValueError("delay_threshold cannot be negative")
        self._clock = clock
        self._delay_threshold = delay_threshold
        self._paid_order_statuses = paid_order_statuses
        self._successful_capture_statuses = successful_capture_statuses
        self._denied_capture_statuses = denied_capture_statuses

    def run(
        self,
        merchant_orders: Sequence[ProvisionalMerchantOrder],
        paypal_payments: Sequence[ProvisionalPayPalPayment],
        business_records: Sequence[ProvisionalMerchantBusinessRecords] = (),
        *,
        webhook_events: Sequence[ProvisionalWebhookEvent] = (),
        paypal_refund_records: Sequence[Mapping[str, Any]] | None = None,
    ) -> ReconciliationResult:
        detected_at = self._clock()
        if detected_at.tzinfo is None or detected_at.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        self._validate_business_records(business_records)
        match_result = match_records(merchant_orders, paypal_payments)

        cases = [
            case
            for transaction in match_result.transactions
            for case in reconcile_transaction(
                transaction,
                detected_at=detected_at,
                delay_threshold=self._delay_threshold,
                paid_order_statuses=self._paid_order_statuses,
                successful_capture_statuses=self._successful_capture_statuses,
                denied_capture_statuses=self._denied_capture_statuses,
            )
        ]
        cases.extend(
            evaluate_webhook_events(
                webhook_events,
                detected_at=detected_at,
                delay_threshold=self._delay_threshold,
            )
        )
        status_event_cases = evaluate_status_events(
            merchant_orders,
            paypal_payments,
            webhook_events,
            detected_at=detected_at,
            delay_threshold=self._delay_threshold,
            paid_order_statuses=self._paid_order_statuses,
        )
        for event_case in status_event_cases:
            if event_case.exception_type == ExceptionType.STATUS_MISMATCH:
                cases = [
                    case
                    for case in cases
                    if not (
                        case.exception_type == ExceptionType.STATUS_MISMATCH
                        and case.merchant_order_id == event_case.merchant_order_id
                        and case.capture_id == event_case.capture_id
                        and (
                            (
                                case.expected_value == event_case.expected_value
                                and case.actual_value == event_case.actual_value
                            )
                            or case.expected_value == "successful capture for paid order"
                        )
                    )
                ]
        cases.extend(status_event_cases)
        cases.extend(
            evaluate_refunds(
                business_records,
                paypal_refund_records,
                detected_at=detected_at,
                payment_records=paypal_payments,
            )
        )
        unique_cases = _deduplicate_cases(cases)
        summary = _summarize(
            order_count=len(merchant_orders),
            payment_count=len(paypal_payments),
            transactions=match_result.transactions,
            unmatched_payment_count=len(match_result.unmatched_payments),
            cases=unique_cases,
        )
        return ReconciliationResult(
            transactions=match_result.transactions,
            exception_cases=tuple(unique_cases),
            summary=summary,
        )

    @staticmethod
    def _validate_business_records(
        records: Sequence[ProvisionalMerchantBusinessRecords],
    ) -> None:
        seen: set[str] = set()
        for record in records:
            if record.merchant_order_id in seen:
                raise ValueError(
                    "Duplicate merchant business record for order "
                    f"{record.merchant_order_id}"
                )
            seen.add(record.merchant_order_id)


def _deduplicate_cases(cases: Sequence[ExceptionCase]) -> list[ExceptionCase]:
    unique: dict[str, ExceptionCase] = {}
    for case in cases:
        unique.setdefault(case.case_id, case)
    return list(unique.values())


def _summarize(
    *,
    order_count: int,
    payment_count: int,
    transactions: Sequence[MatchedTransaction],
    unmatched_payment_count: int,
    cases: Sequence[ExceptionCase],
) -> ReconciliationSummary:
    by_type = Counter(case.exception_type.value for case in cases)
    by_severity = Counter(case.severity.value for case in cases)
    matched_order_count = sum(
        transaction.merchant_order is not None and bool(transaction.payments)
        for transaction in transactions
    )
    return ReconciliationSummary(
        order_count=order_count,
        payment_count=payment_count,
        matched_order_count=matched_order_count,
        unmatched_payment_count=unmatched_payment_count,
        exception_count=len(cases),
        exceptions_by_type=dict(sorted(by_type.items())),
        exceptions_by_severity=dict(sorted(by_severity.items())),
    )

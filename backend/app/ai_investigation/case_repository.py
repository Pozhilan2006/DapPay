from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.models import ReconciliationExceptionRecord
from app.reconciliation.rules import ExceptionCase


def persist_exception_cases(
    session: Session, cases: tuple[ExceptionCase, ...] | list[ExceptionCase]
) -> None:
    """Append stable reconciliation cases for investigation lookup.

    Existing records are immutable reconciliation observations: their original
    classification, severity, status, and Decimal-safe JSON values are never
    overwritten. The savepoint also makes a concurrent repeat insert harmless.
    """
    for case in cases:
        existing = session.get(ReconciliationExceptionRecord, case.case_id)
        if existing is not None:
            continue
        try:
            with session.begin_nested():
                session.add(
                    ReconciliationExceptionRecord(
                        case_id=case.case_id,
                        exception_type=case.exception_type.value,
                        severity=case.severity.value,
                        merchant_order_id=case.merchant_order_id,
                        paypal_order_id=case.paypal_order_id,
                        capture_id=case.capture_id,
                        expected_value=_json_safe(case.expected_value),
                        actual_value=_json_safe(case.actual_value),
                        evidence_identifiers=list(case.evidence_identifiers),
                        explanation=case.explanation,
                        case_status=case.status,
                        detected_at=case.detected_at,
                        created_at=datetime.now(timezone.utc),
                    )
                )
                session.flush()
        except IntegrityError:
            # Another reconciliation worker inserted the same stable case ID.
            # Keeping the original immutable observation is the idempotent path.
            continue


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Persisted case timestamps must be timezone-aware.")
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, float):
        raise ValueError("Financial case values cannot be binary floats.")
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise TypeError("Case values must be JSON-compatible.")

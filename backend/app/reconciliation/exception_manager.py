"""In-memory exception case management; intentionally no database persistence."""

from collections import Counter
from dataclasses import replace
from typing import Any, Callable, Hashable, Iterable

from app.reconciliation.rules import (
    ExceptionCase,
    ExceptionType,
    Severity,
    create_exception,
)

CASE_STATUSES = frozenset({"open", "in_review", "resolved", "ignored"})


class ExceptionManager:
    def __init__(self, cases: Iterable[ExceptionCase] = ()) -> None:
        self._cases: dict[str, ExceptionCase] = {}
        for case in cases:
            self.add(case)

    def add(self, case: ExceptionCase) -> ExceptionCase:
        if case.status not in CASE_STATUSES:
            raise ValueError(f"Unsupported exception case status: {case.status}")
        existing = self._cases.get(case.case_id)
        if existing is not None and existing != case:
            raise ValueError(f"Conflicting exception case ID: {case.case_id}")
        self._cases[case.case_id] = case
        return case

    def create(self, exception_type: ExceptionType, **values: Any) -> ExceptionCase:
        return self.add(create_exception(exception_type, **values))

    def get(self, case_id: str) -> ExceptionCase | None:
        return self._cases.get(case_id)

    def update_status(self, case_id: str, status: str) -> ExceptionCase:
        if status not in CASE_STATUSES:
            raise ValueError(f"Unsupported exception case status: {status}")
        case = self._cases.get(case_id)
        if case is None:
            raise KeyError(f"Unknown exception case: {case_id}")
        updated = replace(case, status=status)
        self._cases[case_id] = updated
        return updated

    def all(self) -> tuple[ExceptionCase, ...]:
        return tuple(self._cases.values())

    def group_by_type(self) -> dict[ExceptionType, tuple[ExceptionCase, ...]]:
        return self._group(lambda case: case.exception_type)

    def group_by_severity(self) -> dict[Severity, tuple[ExceptionCase, ...]]:
        return self._group(lambda case: case.severity)

    def evidence_references(self, case_id: str) -> tuple[str, ...]:
        case = self._cases.get(case_id)
        if case is None:
            raise KeyError(f"Unknown exception case: {case_id}")
        return case.evidence_identifiers

    def summary_counts(self) -> dict[str, dict[str, int] | int]:
        by_type = Counter(case.exception_type.value for case in self._cases.values())
        by_severity = Counter(case.severity.value for case in self._cases.values())
        by_status = Counter(case.status for case in self._cases.values())
        return {
            "total": len(self._cases),
            "by_type": dict(sorted(by_type.items())),
            "by_severity": dict(sorted(by_severity.items())),
            "by_status": dict(sorted(by_status.items())),
        }

    def _group(
        self, key: Callable[[ExceptionCase], Hashable]
    ) -> dict[Hashable, tuple[ExceptionCase, ...]]:
        grouped: dict[Hashable, list[ExceptionCase]] = {}
        for case in self._cases.values():
            grouped.setdefault(key(case), []).append(case)
        return {group: tuple(cases) for group, cases in grouped.items()}

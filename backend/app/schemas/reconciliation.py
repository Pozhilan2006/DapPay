from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReconciliationRunResponse(BaseModel):
    order_count: int
    payment_count: int
    matched_order_count: int
    unmatched_payment_count: int
    exception_count: int
    exceptions_by_type: dict[str, int]
    exceptions_by_severity: dict[str, int]
    persisted_case_ids: list[str] = Field(default_factory=list)


class TransactionReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paypal_order_id: str
    merchant_order_id: str
    capture_ids: list[str]
    expected_amount: Decimal | None
    captured_amount: Decimal
    currency: str | None
    order_status: str | None
    capture_statuses: list[str]
    verification_status: str
    checks: dict[str, bool]
    note: str

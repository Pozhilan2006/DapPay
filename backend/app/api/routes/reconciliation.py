import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.reconciliation import ReconciliationRunResponse
from app.services.reconciliation_workflow import run_persisted_reconciliation

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])
logger = logging.getLogger(__name__)


@router.get("")
def get_reconciliation_status() -> dict[str, str]:
    return {"status": "ready", "message": "Persisted reconciliation is available."}


@router.post("/run", response_model=ReconciliationRunResponse)
def run_reconciliation(
    db: Session = Depends(get_db),
) -> ReconciliationRunResponse:
    try:
        result = run_persisted_reconciliation(db)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Persisted reconciliation failed.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reconciliation storage is temporarily unavailable.",
        ) from None
    summary = result.summary
    return ReconciliationRunResponse(
        order_count=summary.order_count,
        payment_count=summary.payment_count,
        matched_order_count=summary.matched_order_count,
        unmatched_payment_count=summary.unmatched_payment_count,
        exception_count=summary.exception_count,
        exceptions_by_type=summary.exceptions_by_type,
        exceptions_by_severity=summary.exceptions_by_severity,
        persisted_case_ids=[case.case_id for case in result.exception_cases],
    )

import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.ai_investigation.schemas import (
    InvestigationReport,
    InvestigationValidationResult,
)
from app.ai_investigation.service import (
    InvestigationCaseNotFound,
    InvestigationRunError,
    InvestigationService,
    report_from_record,
)
from app.database.session import get_db
from app.core.security import Principal, Role, require_roles
from app.models import InvestigationReportRecord, ReconciliationExceptionRecord
from app.schemas.reconciliation import TransactionReview
from app.services.reconciliation_workflow import review_completed_transaction

router = APIRouter(prefix="/investigations", tags=["Investigations"])
logger = logging.getLogger(__name__)
_CASE_ID_PATTERN = r"^recon_[a-f0-9]{20}$"
_READ_ROLES = (Role.ADMIN, Role.MERCHANT, Role.READ_ONLY)
_WRITE_ROLES = (Role.ADMIN, Role.MERCHANT)


@router.post(
    "/reviews/orders/{paypal_order_id}",
    response_model=TransactionReview,
)
def review_transaction(
    paypal_order_id: str = Path(min_length=1, max_length=128),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> TransactionReview:
    """Verify a completed payment without representing it as an exception."""
    try:
        return review_completed_transaction(
            db,
            paypal_order_id,
            merchant_id=(
                None if principal.role == Role.ADMIN else principal.merchant_id
            ),
        )
    except LookupError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Persisted PayPal order not found.",
        ) from None
    except SQLAlchemyError:
        logger.error("Transaction review source data could not be read.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Transaction review storage is temporarily unavailable.",
        ) from None


@router.post(
    "/{case_id}/run",
    response_model=InvestigationReport,
    status_code=status.HTTP_201_CREATED,
)
async def run_investigation(
    case_id: str = Path(min_length=1, max_length=64, pattern=_CASE_ID_PATTERN),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_WRITE_ROLES)),
) -> InvestigationReport:
    try:
        return await InvestigationService().run(
            db,
            case_id,
            merchant_id=(
                None if principal.role == Role.ADMIN else principal.merchant_id
            ),
        )
    except InvestigationCaseNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconciliation exception case not found.",
        ) from None
    except InvestigationRunError as error:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
                if error.provider_failure
                else status.HTTP_502_BAD_GATEWAY
            ),
            detail=str(error),
        ) from None
    except SQLAlchemyError:
        db.rollback()
        logger.error("Investigation could not be persisted or source data read.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation storage is temporarily unavailable.",
        ) from None


@router.post(
    "/{case_id}/validate",
    response_model=InvestigationValidationResult,
)
def validate_investigation_evidence(
    case_id: str = Path(min_length=1, max_length=64, pattern=_CASE_ID_PATTERN),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> InvestigationValidationResult:
    try:
        return InvestigationService().validate(
            db,
            case_id,
            merchant_id=(
                None if principal.role == Role.ADMIN else principal.merchant_id
            ),
        )
    except InvestigationCaseNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reconciliation exception case not found.",
        ) from None
    except SQLAlchemyError:
        logger.error("Investigation evidence could not be read.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation storage is temporarily unavailable.",
        ) from None
    except ValueError:
        logger.error("Investigation evidence failed consistency validation.")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Investigation evidence is inconsistent.",
        ) from None


@router.get(
    "/{case_id}/reports",
    response_model=list[InvestigationReport],
)
def get_investigation_history(
    case_id: str = Path(min_length=1, max_length=64, pattern=_CASE_ID_PATTERN),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> list[InvestigationReport]:
    try:
        case_query = select(ReconciliationExceptionRecord).where(
            ReconciliationExceptionRecord.case_id == case_id
        )
        if principal.role != Role.ADMIN:
            case_query = case_query.where(
                ReconciliationExceptionRecord.merchant_id == principal.merchant_id
            )
        if db.scalar(case_query) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Reconciliation exception case not found.",
            )
        reports = db.scalars(
            select(InvestigationReportRecord)
            .where(InvestigationReportRecord.case_id == case_id)
            .order_by(
                InvestigationReportRecord.created_at.desc(),
                InvestigationReportRecord.report_id.desc(),
            )
            .limit(limit)
            .offset(offset)
        ).all()
    except SQLAlchemyError:
        logger.error("Investigation history could not be read.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation storage is temporarily unavailable.",
        ) from None
    return [report_from_record(report) for report in reports]


@router.get(
    "/reports/{report_id}",
    response_model=InvestigationReport,
)
def get_investigation_report(
    report_id: str = Path(min_length=1, max_length=36),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> InvestigationReport:
    try:
        query = (
            select(InvestigationReportRecord)
            .join(
                ReconciliationExceptionRecord,
                ReconciliationExceptionRecord.case_id
                == InvestigationReportRecord.case_id,
            )
            .where(InvestigationReportRecord.report_id == report_id)
        )
        if principal.role != Role.ADMIN:
            query = query.where(
                ReconciliationExceptionRecord.merchant_id == principal.merchant_id
            )
        report = db.scalar(query)
    except SQLAlchemyError:
        logger.error("Investigation report could not be read.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation storage is temporarily unavailable.",
        ) from None
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investigation report not found.",
        )
    return report_from_record(report)


@router.get(
    "/{case_id}",
    response_model=InvestigationReport,
)
def get_latest_investigation(
    case_id: str = Path(min_length=1, max_length=64, pattern=_CASE_ID_PATTERN),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> InvestigationReport:
    try:
        query = (
            select(InvestigationReportRecord)
            .join(
                ReconciliationExceptionRecord,
                ReconciliationExceptionRecord.case_id
                == InvestigationReportRecord.case_id,
            )
            .where(InvestigationReportRecord.case_id == case_id)
            .order_by(
                InvestigationReportRecord.created_at.desc(),
                InvestigationReportRecord.report_id.desc(),
            )
            .limit(1)
        )
        if principal.role != Role.ADMIN:
            query = query.where(
                ReconciliationExceptionRecord.merchant_id == principal.merchant_id
            )
        report = db.scalar(query)
    except SQLAlchemyError:
        logger.error("Latest investigation report could not be read.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Investigation storage is temporarily unavailable.",
        ) from None
    if report is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investigation report not found.",
        )
    return report_from_record(report)

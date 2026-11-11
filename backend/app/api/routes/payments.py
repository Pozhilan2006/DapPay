import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.core.security import Principal, Role, require_roles
from app.models import MerchantOrder, PaymentCapture
from app.schemas.persistence import PaymentCaptureResponse

router = APIRouter(prefix="/payments", tags=["Payments"])
logger = logging.getLogger(__name__)
_READ_ROLES = (Role.ADMIN, Role.MERCHANT, Role.READ_ONLY)


@router.get("")
def list_payments(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> list[PaymentCaptureResponse]:
    try:
        query = (
            select(PaymentCapture)
            .join(
                MerchantOrder,
                MerchantOrder.paypal_order_id == PaymentCapture.paypal_order_id,
            )
            .order_by(PaymentCapture.created_at.desc(), PaymentCapture.id.desc())
        )
        if principal.role != Role.ADMIN:
            query = query.where(MerchantOrder.merchant_id == principal.merchant_id)
        captures = db.scalars(query.limit(limit).offset(offset)).all()
    except SQLAlchemyError:
        logger.error("Unable to read persisted PayPal captures.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment storage is temporarily unavailable.",
        ) from None
    return [_serialize_capture(capture) for capture in captures]


@router.get("/{payment_id}")
def get_payment(
    payment_id: str = Path(min_length=1, max_length=128),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> PaymentCaptureResponse:
    try:
        query = (
            select(PaymentCapture)
            .join(
                MerchantOrder,
                MerchantOrder.paypal_order_id == PaymentCapture.paypal_order_id,
            )
            .where(PaymentCapture.paypal_capture_id == payment_id)
        )
        if principal.role != Role.ADMIN:
            query = query.where(MerchantOrder.merchant_id == principal.merchant_id)
        capture = db.scalar(query)
    except SQLAlchemyError:
        logger.error("Unable to read persisted PayPal capture.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment storage is temporarily unavailable.",
        ) from None
    if capture is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Payment capture not found.",
        )
    return _serialize_capture(capture)


def _serialize_capture(capture: PaymentCapture) -> PaymentCaptureResponse:
    return PaymentCaptureResponse(
        payment_id=capture.paypal_capture_id,
        order_id=capture.paypal_order_id,
        status=capture.status,
        amount=capture.amount,
        refunded_amount=capture.refunded_amount,
        currency=capture.currency,
        paypal_created_at=capture.paypal_created_at,
        paypal_updated_at=capture.paypal_updated_at,
    )

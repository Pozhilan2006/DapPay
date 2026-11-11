import logging

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.core.security import Principal, Role, require_roles
from app.models import MerchantOrder
from app.schemas.persistence import MerchantOrderResponse

router = APIRouter(prefix="/orders", tags=["Orders"])
logger = logging.getLogger(__name__)
_READ_ROLES = (Role.ADMIN, Role.MERCHANT, Role.READ_ONLY)


@router.get("")
def list_orders(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> list[MerchantOrderResponse]:
    try:
        query = select(MerchantOrder).order_by(
            MerchantOrder.created_at.desc(), MerchantOrder.id.desc()
        )
        if principal.role != Role.ADMIN:
            query = query.where(MerchantOrder.merchant_id == principal.merchant_id)
        orders = db.scalars(query.limit(limit).offset(offset)).all()
    except SQLAlchemyError:
        logger.error("Unable to read persisted PayPal orders.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order storage is temporarily unavailable.",
        ) from None
    return [_serialize_order(order) for order in orders]


@router.get("/{order_id}")
def get_order(
    order_id: str = Path(min_length=1, max_length=128),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> MerchantOrderResponse:
    try:
        query = select(MerchantOrder).where(MerchantOrder.paypal_order_id == order_id)
        if principal.role != Role.ADMIN:
            query = query.where(MerchantOrder.merchant_id == principal.merchant_id)
        order = db.scalar(query)
    except SQLAlchemyError:
        logger.error("Unable to read persisted PayPal order.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order storage is temporarily unavailable.",
        ) from None
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found.",
        )
    return _serialize_order(order)


def _serialize_order(order: MerchantOrder) -> MerchantOrderResponse:
    return MerchantOrderResponse(
        order_id=order.paypal_order_id,
        merchant_reference=order.merchant_reference,
        invoice_id=order.invoice_id,
        amount=order.amount,
        currency=order.currency,
        intent=order.intent,
        status=order.status,
        paypal_created_at=order.paypal_created_at,
        paypal_updated_at=order.paypal_updated_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )

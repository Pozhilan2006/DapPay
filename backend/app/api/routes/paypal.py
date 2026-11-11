import logging

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.core.security import Principal, Role, require_roles
from app.integrations.paypal.client import (
    PayPalApiError,
    PayPalAuthenticationError,
    PayPalClient,
)
from app.integrations.paypal.orders import capture_order, create_order, get_order
from app.models import MerchantOrder
from app.schemas.paypal import (
    CapturePayPalOrderResponse,
    CreatePayPalOrderRequest,
    CreatePayPalOrderResponse,
    PayPalOrderCaptureSummary,
    PayPalOrderResponse,
    PayPalPurchaseUnitSummary,
)
from app.services.payment_persistence import upsert_capture, upsert_order

router = APIRouter(prefix="/paypal", tags=["PayPal"])
logger = logging.getLogger(__name__)
_WRITE_ROLES = (Role.ADMIN, Role.MERCHANT)
_READ_ROLES = (Role.ADMIN, Role.MERCHANT, Role.READ_ONLY)


@router.post(
    "/orders",
    response_model=CreatePayPalOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_paypal_order(
    request: CreatePayPalOrderRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_WRITE_ROLES)),
) -> CreatePayPalOrderResponse:
    try:
        order = create_order(
            amount=request.amount,
            currency=request.currency,
            merchant_reference=request.merchant_reference,
            invoice_id=request.invoice_id,
            return_url=request.return_url,
            cancel_url=request.cancel_url,
            client=PayPalClient(),
        )
    except PayPalAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from None
    except PayPalApiError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from None
    try:
        upsert_order(
            db,
            paypal_order_id=order.order_id,
            merchant_id=(
                principal.merchant_id if principal.role == Role.MERCHANT else None
            ),
            merchant_reference=request.merchant_reference,
            invoice_id=request.invoice_id,
            amount=request.amount,
            currency=request.currency,
            intent="CAPTURE",
            status=order.status,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.error("PayPal order was created but could not be persisted.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order persistence is temporarily unavailable.",
        ) from None
    except ValueError:
        db.rollback()
        logger.error("PayPal order ownership conflicted during persistence.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order could not be assigned to this merchant.",
        ) from None
    return CreatePayPalOrderResponse(
        order_id=order.order_id,
        status=order.status,
        approval_url=order.approval_url,
    )


@router.post(
    "/orders/{order_id}/capture",
    response_model=CapturePayPalOrderResponse,
)
def capture_paypal_order(
    order_id: str = Path(min_length=1, max_length=128),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_WRITE_ROLES)),
) -> CapturePayPalOrderResponse:
    if principal.role != Role.ADMIN:
        owned_order = db.scalar(
            select(MerchantOrder.paypal_order_id).where(
                MerchantOrder.paypal_order_id == order_id,
                MerchantOrder.merchant_id == principal.merchant_id,
            )
        )
        if owned_order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )
    try:
        capture = capture_order(order_id, client=PayPalClient())
    except PayPalAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from None
    except PayPalApiError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from None
    try:
        upsert_capture(
            db,
            paypal_order_id=capture.order_id,
            paypal_capture_id=capture.capture_id,
            status=capture.status,
            amount=capture.amount,
            currency=capture.currency,
            paypal_created_at=capture.create_time,
            paypal_updated_at=capture.update_time,
        )
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.error("PayPal capture succeeded but could not be persisted.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Capture persistence is temporarily unavailable.",
        ) from None
    return CapturePayPalOrderResponse(
        order_id=capture.order_id,
        capture_id=capture.capture_id,
        capture_status=capture.status,
        captured_amount=capture.amount,
        currency=capture.currency,
        create_time=capture.create_time.isoformat() if capture.create_time else None,
        update_time=capture.update_time.isoformat() if capture.update_time else None,
    )


@router.get(
    "/orders/{order_id}",
    response_model=PayPalOrderResponse,
)
def get_paypal_order(
    order_id: str = Path(min_length=1, max_length=128),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> PayPalOrderResponse:
    if principal.role != Role.ADMIN:
        owned_order = db.scalar(
            select(MerchantOrder.paypal_order_id).where(
                MerchantOrder.paypal_order_id == order_id,
                MerchantOrder.merchant_id == principal.merchant_id,
            )
        )
        if owned_order is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Order not found.",
            )
    try:
        order = get_order(order_id, client=PayPalClient())
    except PayPalAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from None
    except PayPalApiError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from None
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from None

    return PayPalOrderResponse(
        order_id=order.order_id,
        status=order.status,
        intent=order.intent,
        create_time=order.create_time.isoformat() if order.create_time else None,
        update_time=order.update_time.isoformat() if order.update_time else None,
        purchase_units=[
            PayPalPurchaseUnitSummary(
                merchant_reference=unit.merchant_reference,
                invoice_id=unit.invoice_id,
                amount=unit.amount,
                currency=unit.currency,
                has_payee=unit.has_payee,
                captures=[
                    PayPalOrderCaptureSummary(
                        capture_id=capture.capture_id,
                        status=capture.status,
                    )
                    for capture in unit.captures
                ],
            )
            for unit in order.purchase_units
        ],
        payment_source_types=list(order.payment_source_types),
        processing_instruction=order.processing_instruction,
    )

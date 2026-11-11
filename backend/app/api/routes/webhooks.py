import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import ValidationError
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.core.security import Principal, Role, require_roles
from app.integrations.paypal.client import (
    PayPalApiError,
    PayPalAuthenticationError,
    PayPalClient,
)
from app.integrations.paypal.webhooks import (
    extract_transmission_headers,
    validate_webhook_signature,
)
from app.models import MerchantOrder, PaymentCapture, WebhookEvent
from app.schemas.persistence import (
    PayPalWebhookEvent,
    WebhookAcknowledgement,
    WebhookEventResponse,
    WebhookEventSummary,
)
from app.services.paypal_webhooks import ingest_verified_event

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
logger = logging.getLogger(__name__)
_MAX_WEBHOOK_BYTES = 1_048_576
_READ_ROLES = (Role.ADMIN, Role.MERCHANT, Role.READ_ONLY)


@router.post(
    "/paypal",
    response_model=WebhookAcknowledgement,
)
async def receive_paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
) -> WebhookAcknowledgement:
    chunks: list[bytes] = []
    body_size = 0
    async for chunk in request.stream():
        body_size += len(chunk)
        if body_size > _MAX_WEBHOOK_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail="Webhook payload exceeds the allowed size.",
            )
        chunks.append(chunk)
    body = b"".join(chunks)
    try:
        payload: Any = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be valid JSON.",
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook body must be a JSON object.",
        )
    try:
        PayPalWebhookEvent.model_validate(payload)
        transmission_headers = extract_transmission_headers(request.headers)
    except (ValidationError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload or signature headers are invalid.",
        ) from None

    paypal_client = PayPalClient()
    try:
        verified = validate_webhook_signature(
            payload, transmission_headers, client=paypal_client
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
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PayPal webhook signature verification failed.",
        )

    try:
        inserted = ingest_verified_event(db, payload, paypal_client=paypal_client)
    except PayPalApiError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from None
    except PayPalAuthenticationError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from None
    except ValueError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verified PayPal event payload is invalid.",
        ) from None
    except SQLAlchemyError:
        db.rollback()
        logger.error("Verified PayPal webhook could not be persisted.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook storage is temporarily unavailable.",
        ) from None

    logger.info(
        "PayPal webhook acknowledged event_id=%s duplicate=%s",
        payload["id"],
        not inserted,
    )
    return WebhookAcknowledgement(
        status="accepted" if inserted else "duplicate",
        duplicate=not inserted,
    )


@router.get("", response_model=list[WebhookEventSummary])
def list_webhooks(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> list[WebhookEventSummary]:
    try:
        query = select(WebhookEvent).order_by(
            WebhookEvent.received_at.desc(), WebhookEvent.id.desc()
        )
        if principal.role != Role.ADMIN:
            query = query.where(_event_scope(principal.merchant_id))
        events = db.scalars(query.limit(limit).offset(offset)).all()
    except SQLAlchemyError:
        logger.error("Unable to read persisted PayPal webhook events.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook storage is temporarily unavailable.",
        ) from None
    return [_serialize_event(event) for event in events]


@router.get("/{event_id}", response_model=WebhookEventResponse)
def get_webhook(
    event_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_roles(*_READ_ROLES)),
) -> WebhookEventResponse:
    try:
        query = select(WebhookEvent).where(WebhookEvent.paypal_event_id == event_id)
        if principal.role != Role.ADMIN:
            query = query.where(_event_scope(principal.merchant_id))
        event = db.scalar(query)
    except SQLAlchemyError:
        logger.error("Unable to read persisted PayPal webhook event.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook storage is temporarily unavailable.",
        ) from None
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Webhook event not found.",
        )
    return WebhookEventResponse(
        **_serialize_event(event).model_dump(),
        payload=event.raw_payload,
    )


def _serialize_event(event: WebhookEvent) -> WebhookEventSummary:
    return WebhookEventSummary(
        event_id=event.paypal_event_id,
        event_type=event.event_type,
        resource_type=event.resource_type,
        resource_id=event.resource_id,
        occurred_at=event.occurred_at,
        received_at=event.received_at,
        verification_status=event.verification_status,
        processing_status=event.processing_status,
        processing_error=event.processing_error,
    )


def _event_scope(merchant_id: str):
    owned_order = exists(
        select(1).where(
            MerchantOrder.paypal_order_id == WebhookEvent.resource_id,
            MerchantOrder.merchant_id == merchant_id,
        )
    )
    owned_capture = exists(
        select(1)
        .select_from(PaymentCapture)
        .join(
            MerchantOrder,
            MerchantOrder.paypal_order_id == PaymentCapture.paypal_order_id,
        )
        .where(
            PaymentCapture.paypal_capture_id == WebhookEvent.resource_id,
            MerchantOrder.merchant_id == merchant_id,
        )
    )
    return or_(owned_order, owned_capture)

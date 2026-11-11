from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.integrations.paypal.client import PayPalApiError, PayPalClient
from app.integrations.paypal.orders import RetrievedOrder, get_order
from app.models import MerchantOrder, PaymentCapture, WebhookEvent
from app.services.payment_persistence import (
    sanitize_event_payload,
    upsert_capture,
    upsert_order,
)

_EVENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CAPTURE_EVENT_STATUSES = {
    "PAYMENT.CAPTURE.PENDING": "PENDING",
    "PAYMENT.CAPTURE.COMPLETED": "COMPLETED",
    "PAYMENT.CAPTURE.DENIED": "DENIED",
    "PAYMENT.CAPTURE.REFUNDED": "REFUNDED",
}


def parse_event_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("PayPal event timestamp must be an ISO-8601 string.")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("PayPal event timestamp is invalid.") from None
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("PayPal event timestamp must include a timezone.")
    return timestamp.astimezone(timezone.utc)


def ingest_verified_event(
    session: Session,
    event: dict[str, Any],
    *,
    paypal_client: PayPalClient,
    received_at: datetime | None = None,
) -> bool:
    event_id = event.get("id")
    event_type = event.get("event_type")
    if (
        not isinstance(event_id, str)
        or not _EVENT_ID_PATTERN.fullmatch(event_id)
        or not isinstance(event_type, str)
        or not event_type
        or len(event_type) > 160
    ):
        raise ValueError("PayPal event ID or event type is invalid.")

    existing = session.scalar(
        select(WebhookEvent).where(WebhookEvent.paypal_event_id == event_id)
    )
    if existing is not None:
        return False

    resource = event.get("resource")
    if resource is not None and not isinstance(resource, dict):
        raise ValueError("PayPal event resource must be an object.")
    occurred_at = parse_event_timestamp(event.get("create_time"))
    received_at = received_at or datetime.now(timezone.utc)
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise ValueError("Webhook receipt timestamp must be timezone-aware.")

    event_row = WebhookEvent(
        paypal_event_id=event_id,
        event_type=event_type,
        resource_type=(
            event.get("resource_type")
            if isinstance(event.get("resource_type"), str)
            else None
        ),
        resource_id=(
            resource.get("id")
            if isinstance(resource, dict) and isinstance(resource.get("id"), str)
            else None
        ),
        occurred_at=occurred_at,
        received_at=received_at.astimezone(timezone.utc),
        verification_status="SUCCESS",
        processing_status="RECEIVED",
        raw_payload=sanitize_event_payload(event),
    )
    session.add(event_row)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        if session.scalar(
            select(WebhookEvent).where(WebhookEvent.paypal_event_id == event_id)
        ):
            return False
        raise

    processing_status = _process_event(
        session, event, paypal_client=paypal_client
    )
    event_row.processing_status = processing_status
    session.commit()
    return True


def _process_event(
    session: Session,
    event: dict[str, Any],
    *,
    paypal_client: PayPalClient,
) -> str:
    event_type = event["event_type"]
    resource = event.get("resource")
    if not isinstance(resource, dict):
        return "IGNORED"
    if event_type == "CHECKOUT.ORDER.APPROVED":
        return (
            "PROCESSED"
            if _process_approved_order(session, event, resource)
            else "IGNORED"
        )
    if event_type not in _CAPTURE_EVENT_STATUSES:
        return "IGNORED"

    status = _CAPTURE_EVENT_STATUSES[event_type]
    completion_event = status == "COMPLETED"
    related_ids = _related_ids(resource)
    order_id = related_ids.get("order_id")
    capture_id = (
        related_ids.get("capture_id")
        if status == "REFUNDED"
        else resource.get("id")
    )
    if (
        not isinstance(order_id, str)
        or not order_id
        or not isinstance(capture_id, str)
        or not capture_id
    ):
        return "IGNORED"

    event_time = parse_event_timestamp(event.get("create_time"))
    updated_at = parse_event_timestamp(resource.get("update_time")) or event_time
    amount, currency = _event_amount(resource)
    capture_created_at = parse_event_timestamp(resource.get("create_time"))
    order_exists = session.scalar(
        select(MerchantOrder.id).where(MerchantOrder.paypal_order_id == order_id)
    )
    retrieved: RetrievedOrder | None = None
    if status == "COMPLETED" or order_exists is None or amount is None or currency is None:
        retrieved = get_order(order_id, client=paypal_client)
        if order_exists is None:
            _upsert_retrieved_order(session, retrieved)
        details = _find_capture(retrieved, capture_id)
        if details is not None:
            if completion_event:
                amount = details.amount
                currency = details.currency
            else:
                amount = amount if amount is not None else details.amount
                currency = currency if currency is not None else details.currency
            capture_created_at = capture_created_at or details.create_time
            updated_at = details.update_time or updated_at
        if completion_event:
            if details is None:
                raise PayPalApiError(
                    "PayPal has not confirmed the capture in the order."
                )
            status = details.status.upper()
            if status not in {"COMPLETED", "PENDING", "DENIED", "DECLINED"}:
                return "IGNORED"

    if status == "REFUNDED":
        refund_amount = amount
        if refund_amount is None:
            return "IGNORED"
        existing_capture = session.scalar(
            select(PaymentCapture).where(
                PaymentCapture.paypal_capture_id == capture_id
            )
        )
        capture_amount = existing_capture.amount if existing_capture else None
        currency = existing_capture.currency if existing_capture else None
        if capture_amount is None or currency is None:
            details_order = retrieved or get_order(order_id, client=paypal_client)
            details = _find_capture(details_order, capture_id)
            if details is None or details.amount is None or details.currency is None:
                return "IGNORED"
            capture_amount = details.amount
            currency = details.currency
        if currency != _event_amount(resource)[1]:
            return "IGNORED"
        is_full_refund = refund_amount >= capture_amount
        upsert_capture(
            session,
            paypal_order_id=order_id,
            paypal_capture_id=capture_id,
            status="REFUNDED" if is_full_refund else "COMPLETED",
            amount=capture_amount,
            currency=currency,
            paypal_updated_at=updated_at,
            source_reference={
                "paypal_event_id": event["id"],
                "event_type": event_type,
            },
            refund_amount=refund_amount,
        )
        return "PROCESSED"

    if amount is None or currency is None:
        return "IGNORED"
    if status not in {"PENDING", "DENIED", "DECLINED", "COMPLETED"}:
        return "IGNORED"
    upsert_capture(
        session,
        paypal_order_id=order_id,
        paypal_capture_id=capture_id,
        status=status,
        amount=amount,
        currency=currency,
        paypal_created_at=capture_created_at,
        paypal_updated_at=updated_at,
        source_reference={
            "paypal_event_id": event["id"],
            "event_type": event_type,
        },
    )
    return "PROCESSED"


def _process_approved_order(
    session: Session, event: dict[str, Any], resource: dict[str, Any]
) -> bool:
    order_id = resource.get("id")
    if not isinstance(order_id, str) or not order_id:
        return False
    purchase_units = resource.get("purchase_units")
    first_unit = purchase_units[0] if isinstance(purchase_units, list) and purchase_units else {}
    if not isinstance(first_unit, dict):
        first_unit = {}
    amount, currency = _event_amount(first_unit)
    upsert_order(
        session,
        paypal_order_id=order_id,
        merchant_reference=(
            first_unit.get("custom_id")
            if isinstance(first_unit.get("custom_id"), str)
            else None
        ),
        invoice_id=(
            first_unit.get("invoice_id")
            if isinstance(first_unit.get("invoice_id"), str)
            else None
        ),
        amount=amount,
        currency=currency,
        intent=resource.get("intent") if isinstance(resource.get("intent"), str) else None,
        status=(
            resource.get("status")
            if isinstance(resource.get("status"), str)
            else "APPROVED"
        ),
        paypal_created_at=parse_event_timestamp(resource.get("create_time")),
        paypal_updated_at=(
            parse_event_timestamp(resource.get("update_time"))
            or parse_event_timestamp(event.get("create_time"))
        ),
    )
    return True


def _related_ids(resource: dict[str, Any]) -> dict[str, Any]:
    supplementary = resource.get("supplementary_data")
    related = supplementary.get("related_ids") if isinstance(supplementary, dict) else None
    return related if isinstance(related, dict) else {}


def _event_amount(resource: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    amount = resource.get("amount")
    if not isinstance(amount, dict):
        return None, None
    raw_amount = amount.get("value")
    currency = amount.get("currency_code")
    if not isinstance(raw_amount, str) or not isinstance(currency, str):
        return None, None
    if len(raw_amount) > 64 or not re.fullmatch(r"[A-Z]{3}", currency):
        return None, None
    try:
        decimal_amount = Decimal(raw_amount)
    except InvalidOperation:
        return None, None
    if not decimal_amount.is_finite() or decimal_amount < 0:
        return None, None
    return decimal_amount, currency


def _upsert_retrieved_order(
    session: Session, order: RetrievedOrder
) -> MerchantOrder:
    purchase_unit = order.purchase_units[0] if order.purchase_units else None
    return upsert_order(
        session,
        paypal_order_id=order.order_id,
        merchant_reference=(
            purchase_unit.merchant_reference if purchase_unit else None
        ),
        invoice_id=purchase_unit.invoice_id if purchase_unit else None,
        amount=purchase_unit.amount if purchase_unit else None,
        currency=purchase_unit.currency if purchase_unit else None,
        intent=order.intent,
        status=order.status,
        paypal_created_at=order.create_time,
        paypal_updated_at=order.update_time,
    )


def _find_capture(order: RetrievedOrder, capture_id: str) -> Any | None:
    for purchase_unit in order.purchase_units:
        for capture in purchase_unit.captures:
            if capture.capture_id == capture_id:
                return capture
    return None

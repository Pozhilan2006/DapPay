from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MerchantOrder, PaymentCapture

_CAPTURE_STATUS_RANK = {
    "PENDING": 1,
    "DENIED": 2,
    "DECLINED": 2,
    "COMPLETED": 3,
    "REFUNDED": 4,
}
_SENSITIVE_EVENT_KEYS = {
    "address",
    "account_id",
    "birth_date",
    "card",
    "cardholder_name",
    "authorization",
    "authorization_header",
    "access_token",
    "client_secret",
    "email",
    "email_address",
    "id_token",
    "name",
    "payer",
    "payer_id",
    "payment_source",
    "phone",
    "phone_number",
    "refresh_token",
    "routing_number",
    "shipping",
    "token",
}


def sanitize_event_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: sanitize_event_payload(item)
            for key, item in value.items()
            if key.lower() not in _SENSITIVE_EVENT_KEYS
        }
    if isinstance(value, list):
        return [sanitize_event_payload(item) for item in value]
    return value


def upsert_order(
    session: Session,
    *,
    paypal_order_id: str,
    merchant_reference: str | None = None,
    invoice_id: str | None = None,
    amount: Decimal | None = None,
    currency: str | None = None,
    intent: str | None = None,
    status: str | None = None,
    paypal_created_at: datetime | None = None,
    paypal_updated_at: datetime | None = None,
) -> MerchantOrder:
    order = session.scalar(
        select(MerchantOrder)
        .where(MerchantOrder.paypal_order_id == paypal_order_id)
        .with_for_update()
    )
    if order is None:
        order = MerchantOrder(paypal_order_id=paypal_order_id)
        session.add(order)
        session.flush()

    incoming_is_older = (
        paypal_updated_at is not None
        and order.paypal_updated_at is not None
        and paypal_updated_at < order.paypal_updated_at
    )
    if merchant_reference is not None and order.merchant_reference is None:
        order.merchant_reference = merchant_reference
    if invoice_id is not None and order.invoice_id is None:
        order.invoice_id = invoice_id
    if not incoming_is_older:
        if amount is not None:
            order.amount = amount
        if currency is not None:
            order.currency = currency
        if intent is not None:
            order.intent = intent
        if status is not None:
            if not (order.status == "COMPLETED" and status != "COMPLETED"):
                order.status = status
    if paypal_created_at is not None and order.paypal_created_at is None:
        order.paypal_created_at = paypal_created_at
    if paypal_updated_at is not None and (
        order.paypal_updated_at is None
        or paypal_updated_at > order.paypal_updated_at
    ):
        order.paypal_updated_at = paypal_updated_at
    order.updated_at = datetime.now(timezone.utc)
    return order


def upsert_capture(
    session: Session,
    *,
    paypal_order_id: str,
    paypal_capture_id: str,
    status: str,
    amount: Decimal | None = None,
    currency: str | None = None,
    paypal_created_at: datetime | None = None,
    paypal_updated_at: datetime | None = None,
    source_reference: dict[str, Any] | None = None,
    refund_amount: Decimal | None = None,
) -> PaymentCapture:
    order = session.scalar(
        select(MerchantOrder)
        .where(MerchantOrder.paypal_order_id == paypal_order_id)
        .with_for_update()
    )
    if order is None:
        order = upsert_order(session, paypal_order_id=paypal_order_id)

    capture = session.scalar(
        select(PaymentCapture)
        .where(PaymentCapture.paypal_capture_id == paypal_capture_id)
        .with_for_update()
    )
    if capture is None:
        capture = PaymentCapture(
            paypal_order_id=paypal_order_id,
            paypal_capture_id=paypal_capture_id,
            status=status,
            amount=amount,
            refunded_amount=refund_amount or Decimal("0"),
            currency=currency,
            paypal_created_at=paypal_created_at,
            paypal_updated_at=paypal_updated_at,
            source_reference=(
                sanitize_event_payload(source_reference)
                if source_reference is not None
                else None
            ),
        )
        session.add(capture)
        if refund_amount is not None and refund_amount > 0:
            if amount is not None and refund_amount >= amount:
                capture.status = "REFUNDED"
    else:
        incoming_time_is_older = (
            paypal_updated_at is not None
            and capture.paypal_updated_at is not None
            and paypal_updated_at < capture.paypal_updated_at
        )
        existing_rank = _CAPTURE_STATUS_RANK.get(capture.status.upper(), 0)
        incoming_rank = _CAPTURE_STATUS_RANK.get(status.upper(), 0)
        if (
            not incoming_time_is_older
            and incoming_rank >= existing_rank
        ):
            capture.status = status
        if amount is not None:
            capture.amount = amount
        if currency is not None:
            capture.currency = currency
        if (
            paypal_created_at is not None
            and capture.paypal_created_at is None
        ):
            capture.paypal_created_at = paypal_created_at
        if paypal_updated_at is not None and (
            capture.paypal_updated_at is None
            or paypal_updated_at > capture.paypal_updated_at
        ):
            capture.paypal_updated_at = paypal_updated_at
        if source_reference is not None:
            capture.source_reference = sanitize_event_payload(source_reference)
        if refund_amount is not None and refund_amount > 0:
            capture.refunded_amount = (capture.refunded_amount or Decimal("0")) + refund_amount
            if capture.amount is not None and capture.refunded_amount >= capture.amount:
                capture.status = "REFUNDED"
        capture.updated_at = datetime.now(timezone.utc)

    if paypal_updated_at is not None and (
        order.paypal_updated_at is None or paypal_updated_at > order.paypal_updated_at
    ):
        order.paypal_updated_at = paypal_updated_at
    if status.upper() in {"COMPLETED", "REFUNDED"} and order.status != "COMPLETED":
        order.status = "COMPLETED"
    order.updated_at = datetime.now(timezone.utc)
    session.flush()
    return capture

"""Database-backed orchestration for the pure reconciliation engine."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_investigation.case_repository import persist_exception_cases
from app.integration_contracts.payment_data import (
    ProvisionalMerchantOrder,
    ProvisionalPayPalPayment,
    ProvisionalWebhookEvent,
)
from app.models import MerchantOrder, PaymentCapture, WebhookEvent
from app.reconciliation.engine import ReconciliationEngine, ReconciliationResult


def run_persisted_reconciliation(session: Session) -> ReconciliationResult:
    """Reconcile persisted facts and atomically append genuine exception cases.

    The repository keys records by the deterministic engine case ID, so reruns
    of the same facts are idempotent. No case is manufactured for investigation.
    """
    orders = session.scalars(
        select(MerchantOrder).order_by(MerchantOrder.paypal_order_id)
    ).all()
    captures = session.scalars(
        select(PaymentCapture).order_by(PaymentCapture.paypal_capture_id)
    ).all()
    events = session.scalars(
        select(WebhookEvent).order_by(WebhookEvent.paypal_event_id)
    ).all()

    reconciled_orders = [order for order in orders if _complete_order(order)]
    order_dtos = tuple(_order_dto(order) for order in reconciled_orders)
    order_keys = {
        order.paypal_order_id: _reconciliation_order_id(order)
        for order in reconciled_orders
    }
    payment_dtos = tuple(
        _payment_dto(capture, merchant_order_id=order_keys.get(capture.paypal_order_id))
        for capture in captures
        if _complete_capture(capture) and capture.paypal_order_id in order_keys
    )
    webhook_dtos = tuple(_webhook_dto(event) for event in events if _complete_event(event))

    result = ReconciliationEngine().run(
        merchant_orders=order_dtos,
        paypal_payments=payment_dtos,
        webhook_events=webhook_dtos,
    )
    persist_exception_cases(session, result.exception_cases)
    session.commit()
    return result


def review_completed_transaction(
    session: Session, paypal_order_id: str
) -> "TransactionReview":
    """Return a read-only deterministic verification for one persisted order."""
    from app.schemas.reconciliation import TransactionReview

    order = session.scalar(
        select(MerchantOrder).where(MerchantOrder.paypal_order_id == paypal_order_id)
    )
    if order is None:
        raise LookupError("Persisted PayPal order not found.")
    captures = session.scalars(
        select(PaymentCapture)
        .where(PaymentCapture.paypal_order_id == paypal_order_id)
        .order_by(PaymentCapture.paypal_capture_id)
    ).all()
    successful = [
        capture
        for capture in captures
        if capture.status.upper() in {"COMPLETED", "CAPTURED"}
        and capture.amount is not None
        and capture.currency is not None
    ]
    total = sum((capture.amount for capture in successful), Decimal("0"))
    currency_matches = bool(successful) and all(
        capture.currency.upper() == (order.currency or "").upper()
        for capture in successful
    )
    amount_matches = order.amount is not None and total == order.amount
    status_matches = (order.status or "").upper() in {"PAID", "COMPLETED"} and bool(successful)
    return TransactionReview(
        paypal_order_id=order.paypal_order_id,
        merchant_order_id=_reconciliation_order_id(order),
        capture_ids=[capture.paypal_capture_id for capture in captures],
        expected_amount=order.amount,
        captured_amount=total,
        currency=order.currency,
        order_status=order.status,
        capture_statuses=[capture.status for capture in captures],
        verification_status=(
            "MATCHED" if amount_matches and currency_matches and status_matches else "INCOMPLETE"
        ),
        checks={
            "amount_matches": amount_matches,
            "currency_matches": currency_matches,
            "status_matches": status_matches,
        },
        note=(
            "Read-only transaction verification; this result does not create or "
            "change a reconciliation exception case."
        ),
    )


def _reconciliation_order_id(order: MerchantOrder) -> str:
    """Prefer merchant reference, retaining a stable ID when it is absent."""
    return order.merchant_reference or order.paypal_order_id


def _order_dto(order: MerchantOrder) -> ProvisionalMerchantOrder:
    assert order.amount is not None
    assert order.currency is not None
    assert order.status is not None
    return ProvisionalMerchantOrder(
        merchant_order_id=_reconciliation_order_id(order),
        expected_amount=order.amount,
        currency=order.currency,
        order_status=order.status,
        order_created_at=order.paypal_created_at or order.created_at,
        customer_reference=order.merchant_reference,
    )


def _payment_dto(
    capture: PaymentCapture, *, merchant_order_id: str | None
) -> ProvisionalPayPalPayment:
    assert merchant_order_id is not None
    assert capture.amount is not None
    assert capture.currency is not None
    return ProvisionalPayPalPayment(
        paypal_order_id=capture.paypal_order_id,
        paypal_capture_id=capture.paypal_capture_id,
        merchant_order_id=merchant_order_id,
        actual_payment_amount=capture.amount,
        currency=capture.currency,
        capture_status=capture.status,
        capture_timestamp=capture.paypal_created_at,
    )


def _webhook_dto(event: WebhookEvent) -> ProvisionalWebhookEvent:
    assert event.resource_id is not None
    assert event.occurred_at is not None
    return ProvisionalWebhookEvent(
        paypal_event_id=event.paypal_event_id,
        event_type=event.event_type,
        related_resource_id=event.resource_id,
        occurred_at=event.occurred_at,
        received_at=event.received_at,
        verification_status=event.verification_status,
        original_event_payload=event.raw_payload,
    )


def _complete_order(order: MerchantOrder) -> bool:
    return all(
        value is not None
        for value in (order.amount, order.currency, order.status)
    )


def _complete_capture(capture: PaymentCapture) -> bool:
    return capture.amount is not None and capture.currency is not None


def _complete_event(event: WebhookEvent) -> bool:
    return (
        event.verification_status.upper() == "SUCCESS"
        and event.resource_id is not None
        and event.occurred_at is not None
    )

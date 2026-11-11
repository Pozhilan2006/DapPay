"""Database-backed orchestration for the pure reconciliation engine."""

from __future__ import annotations

from collections import Counter
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
from app.schemas.reconciliation import TransactionReview
from app.reconciliation.engine import (
    ReconciliationEngine,
    ReconciliationResult,
    ReconciliationSummary,
)


def run_persisted_reconciliation(
    session: Session, *, merchant_id: str | None = None
) -> ReconciliationResult:
    """Reconcile persisted facts and atomically append genuine exception cases.

    The repository keys records by the deterministic engine case ID, so reruns
    of the same facts are idempotent. No case is manufactured for investigation.
    """
    order_query = select(MerchantOrder).order_by(MerchantOrder.paypal_order_id)
    if merchant_id is not None:
        order_query = order_query.where(MerchantOrder.merchant_id == merchant_id)
    orders = session.scalars(order_query).all()
    order_ids = tuple(order.paypal_order_id for order in orders)
    captures = (
        session.scalars(
            select(PaymentCapture)
            .where(PaymentCapture.paypal_order_id.in_(order_ids))
            .order_by(PaymentCapture.paypal_capture_id)
        ).all()
        if order_ids
        else []
    )
    resource_owner = {order.paypal_order_id: order.merchant_id for order in orders}
    resource_owner.update(
        {
            capture.paypal_capture_id: resource_owner.get(capture.paypal_order_id)
            for capture in captures
        }
    )
    event_query = select(WebhookEvent).order_by(WebhookEvent.paypal_event_id)
    if merchant_id is not None:
        event_query = event_query.where(
            WebhookEvent.resource_id.in_(
                tuple(
                    resource_id
                    for resource_id, owner in resource_owner.items()
                    if owner == merchant_id
                )
            )
        )
    events = session.scalars(event_query).all()

    orders_by_owner: dict[str | None, list[MerchantOrder]] = {}
    for order in orders:
        orders_by_owner.setdefault(order.merchant_id, []).append(order)
    if merchant_id is not None:
        owners = [merchant_id]
        orders_by_owner.setdefault(merchant_id, [])
    else:
        owners = sorted(orders_by_owner, key=lambda value: value or "")
        for event in events:
            owner = resource_owner.get(event.resource_id)
            if owner not in owners:
                owners.append(owner)
                orders_by_owner.setdefault(owner, [])
        if not owners:
            owners = [None]

    results: list[ReconciliationResult] = []
    owner_by_evidence: dict[str, str] = {}
    for owner in owners:
        owner_orders = orders_by_owner.get(owner, [])
        owner_order_ids = {order.paypal_order_id for order in owner_orders}
        owner_captures = [
            capture
            for capture in captures
            if capture.paypal_order_id in owner_order_ids
        ]
        owner_capture_ids = {capture.paypal_capture_id for capture in owner_captures}
        owner_events = [
            event
            for event in events
            if event.resource_id in owner_order_ids | owner_capture_ids
            or (owner is None and event.resource_id not in resource_owner)
        ]
        reconciled_orders = [order for order in owner_orders if _complete_order(order)]
        order_dtos = tuple(_order_dto(order) for order in reconciled_orders)
        order_keys = {
            order.paypal_order_id: _reconciliation_order_id(order)
            for order in reconciled_orders
        }
        payment_dtos = tuple(
            _payment_dto(
                capture,
                merchant_order_id=order_keys.get(capture.paypal_order_id),
            )
            for capture in owner_captures
            if _complete_capture(capture) and capture.paypal_order_id in order_keys
        )
        webhook_dtos = tuple(
            _webhook_dto(event) for event in owner_events if _complete_event(event)
        )
        results.append(
            ReconciliationEngine().run(
                merchant_orders=order_dtos,
                paypal_payments=payment_dtos,
                webhook_events=webhook_dtos,
            )
        )
        if owner is not None:
            owner_by_evidence.update(
                {
                    resource_id: owner
                    for resource_id in owner_order_ids | owner_capture_ids
                }
            )
            owner_by_evidence.update(
                {event.paypal_event_id: owner for event in owner_events}
            )
    cases = tuple(case for result in results for case in result.exception_cases)
    summary = ReconciliationSummary(
        order_count=sum(result.summary.order_count for result in results),
        payment_count=sum(result.summary.payment_count for result in results),
        matched_order_count=sum(
            result.summary.matched_order_count for result in results
        ),
        unmatched_payment_count=sum(
            result.summary.unmatched_payment_count for result in results
        ),
        exception_count=sum(result.summary.exception_count for result in results),
        exceptions_by_type=dict(
            sum(
                (Counter(result.summary.exceptions_by_type) for result in results),
                Counter(),
            )
        ),
        exceptions_by_severity=dict(
            sum(
                (Counter(result.summary.exceptions_by_severity) for result in results),
                Counter(),
            )
        ),
    )
    result = ReconciliationResult(
        transactions=tuple(
            transaction for item in results for transaction in item.transactions
        ),
        exception_cases=cases,
        summary=summary,
    )
    persist_exception_cases(
        session,
        result.exception_cases,
        merchant_id=merchant_id,
        merchant_id_by_evidence=owner_by_evidence,
    )
    session.commit()
    return result


def review_completed_transaction(
    session: Session, paypal_order_id: str, *, merchant_id: str | None = None
) -> TransactionReview:
    """Return a read-only deterministic verification for one persisted order."""
    order_query = select(MerchantOrder).where(
        MerchantOrder.paypal_order_id == paypal_order_id
    )
    if merchant_id is not None:
        order_query = order_query.where(MerchantOrder.merchant_id == merchant_id)
    order = session.scalar(order_query)
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
    status_matches = (order.status or "").upper() in {"PAID", "COMPLETED"} and bool(
        successful
    )
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
            "MATCHED"
            if amount_matches and currency_matches and status_matches
            else "INCOMPLETE"
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
        value is not None for value in (order.amount, order.currency, order.status)
    )


def _complete_capture(capture: PaymentCapture) -> bool:
    return capture.amount is not None and capture.currency is not None


def _complete_event(event: WebhookEvent) -> bool:
    return (
        event.verification_status.upper() == "SUCCESS"
        and event.resource_id is not None
        and event.occurred_at is not None
    )

"""Synthetic reconciliation scenarios; none are real PayPal transactions."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.integration_contracts.payment_data import (
    ProvisionalMerchantBusinessRecords,
    ProvisionalMerchantOrder,
    ProvisionalPayPalPayment,
    ProvisionalWebhookEvent,
)

SYNTHETIC_NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class SyntheticScenario:
    merchant_orders: tuple[ProvisionalMerchantOrder, ...]
    paypal_payments: tuple[ProvisionalPayPalPayment, ...]
    business_records: tuple[ProvisionalMerchantBusinessRecords, ...] = ()
    webhook_events: tuple[ProvisionalWebhookEvent, ...] = ()
    paypal_refund_records: tuple[dict[str, Any], ...] | None = None


def _order(
    order_id: str = "SYNTH-MERCHANT-ORDER-001",
    *,
    amount: str = "100.00",
    currency: str = "USD",
    status: str = "paid",
) -> ProvisionalMerchantOrder:
    return ProvisionalMerchantOrder(
        merchant_order_id=order_id,
        expected_amount=Decimal(amount),
        currency=currency,
        order_status=status,
        order_created_at=SYNTHETIC_NOW - timedelta(hours=1),
    )


def _payment(
    *,
    order_id: str = "SYNTH-MERCHANT-ORDER-001",
    paypal_order_id: str = "SYNTH-PAYPAL-ORDER-001",
    capture_id: str | None = "SYNTH-CAPTURE-001",
    amount: str = "100.00",
    currency: str = "USD",
    status: str = "COMPLETED",
    captured_at: datetime | None = SYNTHETIC_NOW - timedelta(minutes=5),
) -> ProvisionalPayPalPayment:
    return ProvisionalPayPalPayment(
        paypal_order_id=paypal_order_id,
        paypal_capture_id=capture_id,
        merchant_order_id=order_id,
        actual_payment_amount=Decimal(amount),
        currency=currency,
        capture_status=status,
        capture_timestamp=captured_at,
    )


def _webhook(
    event_id: str,
    occurred_at: datetime,
    received_at: datetime,
) -> ProvisionalWebhookEvent:
    return ProvisionalWebhookEvent(
        paypal_event_id=event_id,
        event_type="SYNTHETIC.CAPTURE.EVENT",
        related_resource_id="SYNTH-CAPTURE-001",
        occurred_at=occurred_at,
        received_at=received_at,
        verification_status="synthetic_unverified",
        original_event_payload={"synthetic_fixture": True},
    )


def build_synthetic_scenarios() -> dict[str, SyntheticScenario]:
    """Build the ten required independent, explicitly synthetic scenarios."""
    earlier = SYNTHETIC_NOW - timedelta(minutes=4)
    later = SYNTHETIC_NOW - timedelta(minutes=2)
    return {
        "successful_payment": SyntheticScenario(
            (_order(),), (_payment(),)
        ),
        "amount_mismatch": SyntheticScenario(
            (_order(),), (_payment(amount="90.00"),)
        ),
        "currency_mismatch": SyntheticScenario(
            (_order(),), (_payment(currency="EUR"),)
        ),
        "missing_payment": SyntheticScenario((_order(),), ()),
        "missing_order": SyntheticScenario(
            (), (_payment(order_id="SYNTH-UNMATCHED-ORDER"),)
        ),
        "status_mismatch": SyntheticScenario(
            (_order(),), (_payment(status="DENIED"),)
        ),
        "refund_discrepancy": SyntheticScenario(
            (_order(),),
            (_payment(),),
            business_records=(
                ProvisionalMerchantBusinessRecords(
                    merchant_order_id="SYNTH-MERCHANT-ORDER-001",
                    accounting_entries=[],
                    refund_records=[
                        {
                            "refund_id": "SYNTH-MERCHANT-REFUND-001",
                            "amount": Decimal("10.00"),
                            "currency": "USD",
                        }
                    ],
                ),
            ),
            paypal_refund_records=(
                {
                    "paypal_refund_id": "SYNTH-PAYPAL-REFUND-001",
                    "merchant_order_id": "SYNTH-MERCHANT-ORDER-001",
                    "amount": Decimal("8.00"),
                    "currency": "USD",
                },
            ),
        ),
        "duplicate_webhook_delivery": SyntheticScenario(
            (_order(),),
            (_payment(),),
            webhook_events=(
                _webhook("SYNTH-EVENT-DUP-001", earlier, earlier + timedelta(seconds=2)),
                _webhook("SYNTH-EVENT-DUP-001", earlier, earlier + timedelta(seconds=7)),
            ),
        ),
        "partial_captures": SyntheticScenario(
            (_order(),),
            (
                _payment(capture_id="SYNTH-CAPTURE-PART-001", amount="40.00"),
                _payment(
                    paypal_order_id="SYNTH-PAYPAL-ORDER-002",
                    capture_id="SYNTH-CAPTURE-PART-002",
                    amount="60.00",
                ),
            ),
        ),
        "out_of_order_events": SyntheticScenario(
            (_order(),),
            (_payment(),),
            webhook_events=(
                _webhook("SYNTH-EVENT-LATER-001", later, earlier),
                _webhook("SYNTH-EVENT-EARLIER-001", earlier, later),
            ),
        ),
    }

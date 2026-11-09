"""Synthetic lineage records; none are real PayPal transactions or webhooks."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.integration_contracts.payment_data import (
    ProvisionalMerchantBusinessRecords,
    ProvisionalMerchantOrder,
    ProvisionalPayPalPayment,
    ProvisionalWebhookEvent,
)

SYNTHETIC_LINEAGE_TIME = datetime(2026, 2, 1, 12, 0, tzinfo=timezone.utc)


def build_synthetic_lineage_records():
    order_id = "SYNTH-LINEAGE-MERCHANT-ORDER-001"
    capture_id = "SYNTH-LINEAGE-CAPTURE-001"
    event_id = "SYNTH-LINEAGE-EVENT-001"
    order = ProvisionalMerchantOrder(
        merchant_order_id=order_id,
        expected_amount=Decimal("100.00"),
        currency="USD",
        order_status="paid",
        order_created_at=SYNTHETIC_LINEAGE_TIME - timedelta(hours=1),
    )
    payment = ProvisionalPayPalPayment(
        paypal_order_id="SYNTH-LINEAGE-PAYPAL-ORDER-001",
        paypal_capture_id=capture_id,
        merchant_order_id=order_id,
        actual_payment_amount=Decimal("100.00"),
        currency="USD",
        capture_status="COMPLETED",
        capture_timestamp=SYNTHETIC_LINEAGE_TIME - timedelta(minutes=5),
    )
    event = ProvisionalWebhookEvent(
        paypal_event_id=event_id,
        event_type="SYNTHETIC.CAPTURE.COMPLETED",
        related_resource_id=capture_id,
        occurred_at=SYNTHETIC_LINEAGE_TIME - timedelta(minutes=4),
        received_at=SYNTHETIC_LINEAGE_TIME - timedelta(minutes=3),
        verification_status="synthetic_unverified",
        original_event_payload={"synthetic_fixture": True},
    )
    business = ProvisionalMerchantBusinessRecords(
        merchant_order_id=order_id,
        fulfillment_status="shipped",
        fulfillment_record_id="SYNTH-LINEAGE-FULFILLMENT-001",
        updated_by_event_id=event_id,
        shipping_information={
            "shipping_record_id": "SYNTH-LINEAGE-SHIPPING-001",
            "fulfillment_record_id": "SYNTH-LINEAGE-FULFILLMENT-001",
            "status": "in_transit",
            "occurred_at": SYNTHETIC_LINEAGE_TIME - timedelta(minutes=2),
            "updated_by_event_id": event_id,
        },
        accounting_entries=[
            {
                "accounting_entry_id": "SYNTH-LINEAGE-ACCOUNTING-001",
                "capture_id": capture_id,
                "amount": Decimal("100.00"),
                "currency": "USD",
                "occurred_at": SYNTHETIC_LINEAGE_TIME - timedelta(minutes=1),
            }
        ],
        refund_records=[
            {
                "refund_id": "SYNTH-LINEAGE-REFUND-001",
                "capture_id": capture_id,
                "amount": Decimal("5.00"),
                "currency": "USD",
                "status": "synthetic_pending",
            }
        ],
    )
    return (order,), (payment,), (event,), (business,)

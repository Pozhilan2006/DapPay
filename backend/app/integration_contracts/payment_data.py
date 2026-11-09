"""Provisional Member 1-to-Member 2 data contracts.

These DTOs are integration interfaces, not SQLAlchemy models or a final schema.
Member 1 must confirm the field names, optionality, and status values before use.
"""

from decimal import Decimal
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict


class ProvisionalContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProvisionalMerchantOrder(ProvisionalContract):
    merchant_order_id: str
    expected_amount: Decimal
    currency: str
    order_status: str
    order_created_at: AwareDatetime
    customer_reference: str | None = None


class ProvisionalPayPalPayment(ProvisionalContract):
    paypal_order_id: str
    paypal_capture_id: str | None
    merchant_order_id: str
    actual_payment_amount: Decimal
    currency: str
    capture_status: str
    capture_timestamp: AwareDatetime | None = None


class ProvisionalWebhookEvent(ProvisionalContract):
    paypal_event_id: str
    event_type: str
    related_resource_id: str
    occurred_at: AwareDatetime
    received_at: AwareDatetime
    verification_status: str
    original_event_payload: dict[str, Any]


class ProvisionalMerchantBusinessRecords(ProvisionalContract):
    merchant_order_id: str
    fulfillment_status: str | None = None
    shipping_information: dict[str, Any] | None = None
    accounting_entries: list[dict[str, Any]]
    refund_records: list[dict[str, Any]]

from decimal import Decimal
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class MerchantOrderResponse(BaseModel):
    order_id: str
    merchant_reference: str | None
    invoice_id: str | None
    amount: Decimal | None
    currency: str | None
    intent: str | None
    status: str | None
    paypal_created_at: AwareDatetime | None
    paypal_updated_at: AwareDatetime | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class PaymentCaptureResponse(BaseModel):
    payment_id: str
    order_id: str
    status: str
    amount: Decimal | None
    refunded_amount: Decimal
    currency: str | None
    paypal_created_at: AwareDatetime | None
    paypal_updated_at: AwareDatetime | None


class WebhookEventSummary(BaseModel):
    event_id: str
    event_type: str
    resource_type: str | None
    resource_id: str | None
    occurred_at: AwareDatetime | None
    received_at: AwareDatetime
    verification_status: str
    processing_status: str
    processing_error: str | None


class WebhookEventResponse(WebhookEventSummary):
    payload: dict[str, Any]


class WebhookAcknowledgement(BaseModel):
    status: str
    duplicate: bool


class PayPalWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=1, max_length=160)
    resource_type: str | None = None
    create_time: AwareDatetime | None = None
    resource: dict[str, Any] | None = None

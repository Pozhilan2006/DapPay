from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class CreatePayPalOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal
    currency: CurrencyCode
    merchant_reference: str | None = Field(default=None, max_length=127)
    invoice_id: str | None = Field(default=None, max_length=127)
    return_url: str
    cancel_url: str

    @field_validator("amount", mode="before")
    @classmethod
    def amount_must_not_be_float(cls, value: Any) -> Any:
        if isinstance(value, (float, bool)):
            raise ValueError("Amount must be supplied as a decimal string.")
        return value

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("Amount must be a finite positive decimal.")
        return value

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.upper()
        return value

    @field_validator("return_url", "cancel_url")
    @classmethod
    def validate_redirect_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("URL must be a valid HTTP(S) URL.")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("URL cannot contain credentials.")
        return value

    @model_validator(mode="after")
    def require_merchant_reference_or_invoice_id(self) -> "CreatePayPalOrderRequest":
        if not self.merchant_reference and not self.invoice_id:
            raise ValueError("A merchant reference or invoice ID is required.")
        return self


class CreatePayPalOrderResponse(BaseModel):
    order_id: str
    status: str
    approval_url: str


class CapturePayPalOrderResponse(BaseModel):
    order_id: str
    capture_id: str
    capture_status: str
    captured_amount: Decimal
    currency: str
    create_time: str | None = None
    update_time: str | None = None


class PayPalOrderCaptureSummary(BaseModel):
    capture_id: str
    status: str


class PayPalPurchaseUnitSummary(BaseModel):
    merchant_reference: str | None = None
    invoice_id: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    has_payee: bool
    captures: list[PayPalOrderCaptureSummary]


class PayPalOrderResponse(BaseModel):
    order_id: str
    status: str
    intent: str | None
    create_time: str | None = None
    update_time: str | None = None
    purchase_units: list[PayPalPurchaseUnitSummary]
    payment_source_types: list[str]
    processing_instruction: str | None = None

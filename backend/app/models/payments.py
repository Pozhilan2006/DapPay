from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import UTCDateTime


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MerchantOrder(Base):
    __tablename__ = "merchant_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paypal_order_id: Mapped[str] = mapped_column(String(128), unique=True)
    merchant_reference: Mapped[str | None] = mapped_column(String(127), nullable=True)
    invoice_id: Mapped[str | None] = mapped_column(String(127), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(32, 12), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    paypal_created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    paypal_updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, onupdate=_utc_now, nullable=False
    )
    captures: Mapped[list["PaymentCapture"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )


class PaymentCapture(Base):
    __tablename__ = "payment_captures"
    __table_args__ = (
        UniqueConstraint("paypal_capture_id", name="uq_payment_captures_paypal_id"),
        Index("ix_payment_captures_paypal_order_id", "paypal_order_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paypal_capture_id: Mapped[str] = mapped_column(String(128), nullable=False)
    paypal_order_id: Mapped[str] = mapped_column(
        ForeignKey("merchant_orders.paypal_order_id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(64), nullable=False)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(32, 12), nullable=True)
    refunded_amount: Mapped[Decimal] = mapped_column(
        Numeric(32, 12), default=Decimal("0"), server_default="0", nullable=False
    )
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    paypal_created_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    paypal_updated_at: Mapped[datetime | None] = mapped_column(
        UTCDateTime(), nullable=True
    )
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, onupdate=_utc_now, nullable=False
    )
    order: Mapped[MerchantOrder] = relationship(back_populates="captures")


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("paypal_event_id", name="uq_webhook_events_paypal_id"),
        Index("ix_webhook_events_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    paypal_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(160), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, nullable=False
    )
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

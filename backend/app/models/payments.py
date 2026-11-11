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
    merchant_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
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
    source_reference: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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


class ReconciliationExceptionRecord(Base):
    __tablename__ = "reconciliation_exception_cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    merchant_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    exception_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    merchant_order_id: Mapped[str | None] = mapped_column(String(128))
    paypal_order_id: Mapped[str | None] = mapped_column(String(128))
    capture_id: Mapped[str | None] = mapped_column(String(128))
    expected_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    actual_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    evidence_identifiers: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    case_status: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, nullable=False
    )


class InvestigationReportRecord(Base):
    __tablename__ = "investigation_reports"
    __table_args__ = (
        Index("ix_investigation_reports_case_created", "case_id", "created_at"),
    )

    report_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(
        ForeignKey("reconciliation_exception_cases.case_id", ondelete="RESTRICT"),
        nullable=False,
    )
    investigation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    probable_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    missing_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    conflicting_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    deterministic_analysis: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confidence_basis: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    requires_human_approval: Mapped[bool] = mapped_column(default=True, nullable=False)
    llm_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    investigated_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=_utc_now, onupdate=_utc_now, nullable=False
    )

"""Add PayPal order, capture, and webhook persistence.

Revision ID: 20261111_01
Revises:
Create Date: 2026-11-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.database.types import UTCDateTime

revision: str = "20261111_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "merchant_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paypal_order_id", sa.String(128), nullable=False, unique=True),
        sa.Column("merchant_reference", sa.String(127), nullable=True),
        sa.Column("invoice_id", sa.String(127), nullable=True),
        sa.Column("amount", sa.Numeric(32, 12), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("paypal_created_at", UTCDateTime(), nullable=True),
        sa.Column("paypal_updated_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_table(
        "payment_captures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paypal_capture_id", sa.String(128), nullable=False),
        sa.Column("paypal_order_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(32, 12), nullable=True),
        sa.Column(
            "refunded_amount",
            sa.Numeric(32, 12),
            nullable=False,
            server_default="0",
        ),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("paypal_created_at", UTCDateTime(), nullable=True),
        sa.Column("paypal_updated_at", UTCDateTime(), nullable=True),
        sa.Column("source_reference", sa.JSON(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["paypal_order_id"],
            ["merchant_orders.paypal_order_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "paypal_capture_id", name="uq_payment_captures_paypal_id"
        ),
    )
    op.create_index(
        "ix_payment_captures_paypal_order_id",
        "payment_captures",
        ["paypal_order_id"],
    )
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("paypal_event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(160), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=True),
        sa.Column("resource_id", sa.String(128), nullable=True),
        sa.Column("occurred_at", UTCDateTime(), nullable=True),
        sa.Column("received_at", UTCDateTime(), nullable=False),
        sa.Column("verification_status", sa.String(32), nullable=False),
        sa.Column("processing_status", sa.String(32), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.UniqueConstraint("paypal_event_id", name="uq_webhook_events_paypal_id"),
    )
    op.create_index(
        "ix_webhook_events_event_type", "webhook_events", ["event_type"]
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_event_type", table_name="webhook_events")
    op.drop_table("webhook_events")
    op.drop_index(
        "ix_payment_captures_paypal_order_id", table_name="payment_captures"
    )
    op.drop_table("payment_captures")
    op.drop_table("merchant_orders")

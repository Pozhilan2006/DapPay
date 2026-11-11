"""Add merchant ownership to persisted orders and reconciliation cases.

Revision ID: 20261111_03
Revises: 20261111_02
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261111_03"
down_revision: Union[str, None] = "20261111_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "merchant_orders",
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_merchant_orders_merchant_id", "merchant_orders", ["merchant_id"]
    )
    op.add_column(
        "reconciliation_exception_cases",
        sa.Column("merchant_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        "ix_reconciliation_exception_cases_merchant_id",
        "reconciliation_exception_cases",
        ["merchant_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconciliation_exception_cases_merchant_id",
        table_name="reconciliation_exception_cases",
    )
    op.drop_column("reconciliation_exception_cases", "merchant_id")
    op.drop_index("ix_merchant_orders_merchant_id", table_name="merchant_orders")
    op.drop_column("merchant_orders", "merchant_id")

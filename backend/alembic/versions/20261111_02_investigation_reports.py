"""Persist reconciliation cases and immutable investigation reports.

Revision ID: 20261111_02
Revises: 20261111_01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.database.types import UTCDateTime

revision: str = "20261111_02"
down_revision: Union[str, None] = "20261111_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "reconciliation_exception_cases",
        sa.Column("case_id", sa.String(64), primary_key=True),
        sa.Column("exception_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("merchant_order_id", sa.String(128), nullable=True),
        sa.Column("paypal_order_id", sa.String(128), nullable=True),
        sa.Column("capture_id", sa.String(128), nullable=True),
        sa.Column("expected_value", _json_type, nullable=True),
        sa.Column("actual_value", _json_type, nullable=True),
        sa.Column("evidence_identifiers", _json_type, nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("case_status", sa.String(32), nullable=False),
        sa.Column("detected_at", UTCDateTime(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
    )
    op.create_index(
        "ix_reconciliation_exception_cases_paypal_order",
        "reconciliation_exception_cases",
        ["paypal_order_id"],
    )
    op.create_index(
        "ix_reconciliation_exception_cases_capture",
        "reconciliation_exception_cases",
        ["capture_id"],
    )
    op.create_table(
        "investigation_reports",
        sa.Column("report_id", sa.String(36), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(64),
            sa.ForeignKey(
                "reconciliation_exception_cases.case_id", ondelete="RESTRICT"
            ),
            nullable=False,
        ),
        sa.Column("investigation_status", sa.String(32), nullable=False),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False),
        sa.Column("probable_cause", sa.Text(), nullable=True),
        sa.Column("findings", _json_type, nullable=False),
        sa.Column("missing_evidence", _json_type, nullable=False),
        sa.Column("conflicting_evidence", _json_type, nullable=False),
        sa.Column("evidence_snapshot", _json_type, nullable=False),
        sa.Column("deterministic_analysis", _json_type, nullable=False),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("confidence_basis", sa.Text(), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("requires_human_approval", sa.Boolean(), nullable=False),
        sa.Column("llm_provider", sa.String(32), nullable=True),
        sa.Column("llm_model", sa.String(128), nullable=True),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("validation_errors", _json_type, nullable=False),
        sa.Column("investigated_at", UTCDateTime(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
    )
    op.create_index(
        "ix_investigation_reports_case_created",
        "investigation_reports",
        ["case_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_investigation_reports_case_created", table_name="investigation_reports"
    )
    op.drop_table("investigation_reports")
    op.drop_index(
        "ix_reconciliation_exception_cases_capture",
        table_name="reconciliation_exception_cases",
    )
    op.drop_index(
        "ix_reconciliation_exception_cases_paypal_order",
        table_name="reconciliation_exception_cases",
    )
    op.drop_table("reconciliation_exception_cases")

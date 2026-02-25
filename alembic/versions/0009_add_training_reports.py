"""Add training_reports table for ML training history.

Persists training run results so the Performance page can show what the
model learned over time — per-model metrics, weight changes, source weight
updates, and Brier score snapshots.

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("triggered_by", sa.String(), nullable=False),
        sa.Column("trigger_reason", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("training_samples", sa.Integer(), server_default="0"),
        sa.Column("test_samples", sa.Integer(), server_default="0"),
        sa.Column("date_range_start", sa.DateTime(), nullable=True),
        sa.Column("date_range_end", sa.DateTime(), nullable=True),
        sa.Column("model_metrics", JSON(), nullable=False),
        sa.Column("weights_before", JSON(), nullable=True),
        sa.Column("weights_after", JSON(), nullable=True),
        sa.Column("source_weights_before", JSON(), nullable=True),
        sa.Column("source_weights_after", JSON(), nullable=True),
        sa.Column("brier_score_before", sa.Float(), nullable=True),
        sa.Column("brier_score_after", sa.Float(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), server_default="0.0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_training_report_completed",
        "training_reports",
        ["completed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_report_completed", table_name="training_reports")
    op.drop_table("training_reports")

"""add workflow node details

Revision ID: 7b1e2a9d4c3f
Revises: 36dc2520c984
Create Date: 2026-08-18 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7b1e2a9d4c3f"
down_revision: str | None = "36dc2520c984"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the complete planned-node fields to workflow nodes."""

    op.add_column(
        "workflow_nodes",
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.execute(sa.text("UPDATE workflow_nodes SET description = prompt WHERE description IS NULL"))
    op.alter_column("workflow_nodes", "description", nullable=False)
    op.add_column(
        "workflow_nodes",
        sa.Column("review_criteria", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    """Remove the complete planned-node fields from workflow nodes."""

    op.drop_column("workflow_nodes", "review_criteria")
    op.drop_column("workflow_nodes", "description")

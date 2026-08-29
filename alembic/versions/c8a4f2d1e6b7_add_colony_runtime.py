"""add colony runtime

Revision ID: c8a4f2d1e6b7
Revises: 7b1e2a9d4c3f
Create Date: 2026-08-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "c8a4f2d1e6b7"
down_revision: str | None = "7b1e2a9d4c3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the Colony execution model alongside read-only legacy DAG data."""

    op.create_table(
        "colonies",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "active",
                "paused",
                "completed",
                "failed",
                "archived",
                name="colony_status",
            ),
            nullable=False,
        ),
        sa.Column("queen_profile", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_colonies")),
    )
    op.create_index("ix_colonies_status", "colonies", ["status"], unique=False)

    op.create_table(
        "agent_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("colony_id", sa.UUID(), nullable=False),
        sa.Column("parent_session_id", sa.UUID(), nullable=True),
        sa.Column("actor_type", sa.String(length=20), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "idle",
                "queued",
                "running",
                "parked",
                "completed",
                "failed",
                "cancelled",
                name="agent_session_status",
            ),
            nullable=False,
        ),
        sa.Column("park_reason", sa.String(length=100), nullable=True),
        sa.Column("task", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cursor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("budget", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["colony_id"],
            ["colonies.id"],
            name=op.f("fk_agent_sessions_colony_id_colonies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_agent_sessions_parent_session_id_agent_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_sessions")),
    )
    op.create_index("ix_agent_sessions_colony_id", "agent_sessions", ["colony_id"])
    op.create_index("ix_agent_sessions_status", "agent_sessions", ["status"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tool_call_id", sa.String(length=200), nullable=True),
        sa.Column("tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_conversation_messages_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_conversation_messages_session_id_agent_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
        sa.UniqueConstraint("session_id", "sequence", name="uq_conversation_session_sequence"),
    )
    op.create_index("ix_conversation_messages_session_id", "conversation_messages", ["session_id"])

    op.create_table(
        "worker_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("colony_id", sa.UUID(), nullable=False),
        sa.Column("queen_session_id", sa.UUID(), nullable=False),
        sa.Column("worker_session_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "reporting",
                "completed",
                "partial",
                "failed",
                "timed_out",
                "cancelled",
                name="worker_status",
            ),
            nullable=False,
        ),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["colony_id"],
            ["colonies.id"],
            name=op.f("fk_worker_runs_colony_id_colonies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["queen_session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_worker_runs_queen_session_id_agent_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_worker_runs_worker_session_id_agent_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_runs")),
        sa.UniqueConstraint("worker_session_id", name=op.f("uq_worker_runs_worker_session_id")),
    )
    op.create_index("ix_worker_runs_colony_id", "worker_runs", ["colony_id"])
    op.create_index("ix_worker_runs_status", "worker_runs", ["status"])

    op.create_table(
        "tracker_entries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("colony_id", sa.UUID(), nullable=False),
        sa.Column("namespace", sa.String(length=100), nullable=False),
        sa.Column("entry_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_session_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["colony_id"],
            ["colonies.id"],
            name=op.f("fk_tracker_entries_colony_id_colonies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_tracker_entries_updated_by_session_id_agent_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tracker_entries")),
        sa.UniqueConstraint(
            "colony_id", "namespace", "entry_key", name="uq_tracker_colony_namespace_key"
        ),
    )
    op.create_index("ix_tracker_entries_colony_id", "tracker_entries", ["colony_id"])

    op.create_table(
        "task_items",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("colony_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "in_progress",
                "completed",
                "blocked",
                "cancelled",
                name="task_item_status",
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("assigned_worker_id", sa.UUID(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["assigned_worker_id"],
            ["worker_runs.id"],
            name=op.f("fk_task_items_assigned_worker_id_worker_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["colony_id"],
            ["colonies.id"],
            name=op.f("fk_task_items_colony_id_colonies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["task_items.id"],
            name=op.f("fk_task_items_parent_id_task_items"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_task_items_session_id_agent_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_items")),
    )
    op.create_index("ix_task_items_colony_id", "task_items", ["colony_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("colony_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("worker_run_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("preview", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["colony_id"],
            ["colonies.id"],
            name=op.f("fk_artifacts_colony_id_colonies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_artifacts_session_id_agent_sessions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["worker_run_id"],
            ["worker_runs.id"],
            name=op.f("fk_artifacts_worker_run_id_worker_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifacts")),
    )
    op.create_index("ix_artifacts_colony_id", "artifacts", ["colony_id"])

    op.create_table(
        "colony_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("colony_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("worker_run_id", sa.UUID(), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("type", sa.String(length=100), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_colony_events_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["colony_id"],
            ["colonies.id"],
            name=op.f("fk_colony_events_colony_id_colonies"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["agent_sessions.id"],
            name=op.f("fk_colony_events_session_id_agent_sessions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["worker_run_id"],
            ["worker_runs.id"],
            name=op.f("fk_colony_events_worker_run_id_worker_runs"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_colony_events")),
        sa.UniqueConstraint("colony_id", "sequence", name="uq_colony_events_colony_sequence"),
    )
    op.create_index("ix_colony_events_colony_id", "colony_events", ["colony_id"])


def downgrade() -> None:
    """Remove Colony tables without touching legacy DAG history."""

    op.drop_index("ix_colony_events_colony_id", table_name="colony_events")
    op.drop_table("colony_events")
    op.drop_index("ix_artifacts_colony_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_task_items_colony_id", table_name="task_items")
    op.drop_table("task_items")
    op.drop_index("ix_tracker_entries_colony_id", table_name="tracker_entries")
    op.drop_table("tracker_entries")
    op.drop_index("ix_worker_runs_status", table_name="worker_runs")
    op.drop_index("ix_worker_runs_colony_id", table_name="worker_runs")
    op.drop_table("worker_runs")
    op.drop_index("ix_conversation_messages_session_id", table_name="conversation_messages")
    op.drop_table("conversation_messages")
    op.drop_index("ix_agent_sessions_status", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_colony_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")
    op.drop_index("ix_colonies_status", table_name="colonies")
    op.drop_table("colonies")
    op.execute("DROP TYPE IF EXISTS task_item_status")
    op.execute("DROP TYPE IF EXISTS worker_status")
    op.execute("DROP TYPE IF EXISTS agent_session_status")
    op.execute("DROP TYPE IF EXISTS colony_status")

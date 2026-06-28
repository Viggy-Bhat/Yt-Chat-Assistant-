"""initial schema: workspaces and messages

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-18 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("youtube_url", sa.String(length=512), nullable=False, unique=True),
        sa.Column("video_id", sa.String(length=16), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("channel", sa.String(length=256), nullable=True),
        sa.Column("duration_s", sa.Integer(), nullable=True),
        sa.Column("thumbnail", sa.String(length=1024), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workspaces_video_id", "workspaces", ["video_id"])
    op.create_index("ix_workspaces_created_at", "workspaces", ["created_at"])

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sources", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_messages_workspace_created", "messages", ["workspace_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_messages_workspace_created", table_name="messages")
    op.drop_table("messages")
    op.drop_index("ix_workspaces_created_at", table_name="workspaces")
    op.drop_index("ix_workspaces_video_id", table_name="workspaces")
    op.drop_table("workspaces")

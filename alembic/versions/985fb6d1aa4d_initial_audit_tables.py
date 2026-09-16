"""initial audit tables: ingestion_runs, hitl_resolutions

Revision ID: 985fb6d1aa4d
Revises:
Create Date: 2026-09-15
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from atlaz.audit.models import SCHEMA

revision = "985fb6d1aa4d"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "ingestion_runs",
        sa.Column("thread_id", sa.String(length=64), primary_key=True),
        sa.Column("repo_path", sa.Text(), nullable=False),
        sa.Column("hitl_enabled", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.Column("nodes_written", sa.Integer(), nullable=True),
        sa.Column("edges_written", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        schema=SCHEMA,
    )

    op.create_table(
        "hitl_resolutions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.String(length=64),
            sa.ForeignKey(f"{SCHEMA}.ingestion_runs.thread_id"),
            nullable=False,
        ),
        sa.Column("item_id", sa.String(length=512), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("reviewer", sa.String(length=256), nullable=False, server_default=""),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_hitl_resolutions_thread_id", "hitl_resolutions", ["thread_id"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_index("ix_hitl_resolutions_thread_id", table_name="hitl_resolutions", schema=SCHEMA)
    op.drop_table("hitl_resolutions", schema=SCHEMA)
    op.drop_table("ingestion_runs", schema=SCHEMA)

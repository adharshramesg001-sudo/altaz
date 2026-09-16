"""evidence store tables + ingestion_runs -> pipeline_runs (LLD Section 14.4)

Revision ID: b2c8f4a91d7e
Revises: 985fb6d1aa4d
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from atlaz.audit.models import SCHEMA

revision = "b2c8f4a91d7e"
down_revision = "985fb6d1aa4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("ingestion_runs", "pipeline_runs", schema=SCHEMA)
    op.add_column(
        "pipeline_runs",
        sa.Column("repo_id", sa.String(length=256), nullable=False, server_default=""),
        schema=SCHEMA,
    )
    op.add_column(
        "pipeline_runs",
        sa.Column("run_mode", sa.String(length=16), nullable=False, server_default="full"),
        schema=SCHEMA,
    )
    op.add_column(
        "pipeline_runs", sa.Column("changed_files_count", sa.Integer(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "pipeline_runs", sa.Column("capability_registry_snapshot", sa.JSON(), nullable=True), schema=SCHEMA
    )

    op.create_table(
        "evidence_records",
        sa.Column("evidence_id", sa.String(length=64), primary_key=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("content_ref", sa.Text(), nullable=True),
        sa.Column("content_inline", sa.Text(), nullable=True),
        sa.Column("produced_by_node", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_evidence_records_run_id", "evidence_records", ["run_id"], schema=SCHEMA)
    op.create_index("ix_evidence_records_file_path", "evidence_records", ["file_path"], schema=SCHEMA)

    op.create_table(
        "llm_traces",
        sa.Column("trace_id", sa.String(length=64), primary_key=True),
        sa.Column(
            "evidence_id", sa.String(length=64), sa.ForeignKey(f"{SCHEMA}.evidence_records.evidence_id"), nullable=True
        ),
        sa.Column("agent_name", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=16), nullable=False),
        sa.Column("prompt_ref", sa.Text(), nullable=False),
        sa.Column("response_ref", sa.Text(), nullable=False),
        sa.Column("model_provider", sa.String(length=32), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_llm_traces_domain_agent", "llm_traces", ["domain", "agent_name"], schema=SCHEMA)

    op.create_table(
        "conflict_records",
        sa.Column("conflict_id", sa.String(length=64), primary_key=True),
        sa.Column("entity_id", sa.String(length=512), nullable=False),
        sa.Column("claim_a_domain", sa.String(length=16), nullable=False),
        sa.Column(
            "claim_a_evidence_id",
            sa.String(length=64),
            sa.ForeignKey(f"{SCHEMA}.evidence_records.evidence_id"),
            nullable=True,
        ),
        sa.Column("claim_a_confidence", sa.Float(), nullable=False),
        sa.Column("claim_b_domain", sa.String(length=16), nullable=False),
        sa.Column(
            "claim_b_evidence_id",
            sa.String(length=64),
            sa.ForeignKey(f"{SCHEMA}.evidence_records.evidence_id"),
            nullable=True,
        ),
        sa.Column("claim_b_confidence", sa.Float(), nullable=False),
        sa.Column("conflict_type", sa.String(length=32), nullable=False),
        sa.Column("resolution_policy", sa.String(length=48), nullable=True),
        sa.Column("resolution_status", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )
    op.create_index("ix_conflict_records_entity_id", "conflict_records", ["entity_id"], schema=SCHEMA)
    op.create_index("ix_conflict_records_status", "conflict_records", ["resolution_status"], schema=SCHEMA)

    op.create_table(
        "parse_failures",
        sa.Column("failure_id", sa.String(length=64), primary_key=True),
        sa.Column("file_id", sa.String(length=512), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("language_detected", sa.String(length=32), nullable=True),
        sa.Column("parser_attempted", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("parse_failures", schema=SCHEMA)
    op.drop_index("ix_conflict_records_status", table_name="conflict_records", schema=SCHEMA)
    op.drop_index("ix_conflict_records_entity_id", table_name="conflict_records", schema=SCHEMA)
    op.drop_table("conflict_records", schema=SCHEMA)
    op.drop_index("ix_llm_traces_domain_agent", table_name="llm_traces", schema=SCHEMA)
    op.drop_table("llm_traces", schema=SCHEMA)
    op.drop_index("ix_evidence_records_file_path", table_name="evidence_records", schema=SCHEMA)
    op.drop_index("ix_evidence_records_run_id", table_name="evidence_records", schema=SCHEMA)
    op.drop_table("evidence_records", schema=SCHEMA)

    op.drop_column("pipeline_runs", "capability_registry_snapshot", schema=SCHEMA)
    op.drop_column("pipeline_runs", "changed_files_count", schema=SCHEMA)
    op.drop_column("pipeline_runs", "run_mode", schema=SCHEMA)
    op.drop_column("pipeline_runs", "repo_id", schema=SCHEMA)
    op.rename_table("pipeline_runs", "ingestion_runs", schema=SCHEMA)

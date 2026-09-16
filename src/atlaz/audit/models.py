"""Audit / evidence-store schema (Postgres, isolated in its own `atlaz`
schema of its own `atlaz` database -- this instance is shared with other
projects, so nothing here touches any database or schema but its own).

`pipeline_runs` replaces the prior build's `ingestion_runs` (LLD Section
14.4's `pipeline_runs` table, extended with `repo_id`, `run_mode`,
`capability_registry_snapshot` for the incremental-run and capability-
registry features) rather than keeping two parallel run-tracking tables.
`hitl_resolutions` stays as-is from the prior build (three-tier HITL
review, orthogonal to the new tables below), FK updated to point at
`pipeline_runs`.

New tables (LLD Section 14.4) cover the evidence-store contract every
semantic claim needs: `evidence_records` is the queryable/joinable source
for every citation (the graph nodes still carry the same citations inline
as `evidence_json`, for cheap reads without a round-trip here);
`llm_traces` is full prompt/response auditability for every LLM-backed
extraction; `conflict_records` is the auditable record of every
cross-domain dispute, resolved or not; `parse_failures` makes gaps in
deterministic analysis queryable instead of silently dropped.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SCHEMA = "atlaz"  # matches DatabaseConfig's default DB_SCHEMA; see module docstring


class Base(DeclarativeBase):
    pass


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012 -- SQLAlchemy's own declarative convention

    thread_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    repo_path: Mapped[str] = mapped_column(Text, nullable=False)
    run_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="full")  # "full"|"incremental"
    hitl_enabled: Mapped[bool] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)  # running|pending_review|complete|failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    nodes_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    edges_written: Mapped[int | None] = mapped_column(Integer, nullable=True)
    changed_files_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    capability_registry_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    resolutions: Mapped[list[HitlResolution]] = relationship(back_populates="run")


class HitlResolution(Base):
    __tablename__ = "hitl_resolutions"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[str] = mapped_column(ForeignKey(f"{SCHEMA}.pipeline_runs.thread_id"), nullable=False)
    item_id: Mapped[str] = mapped_column(String(512), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # accept|edit|reject|resolve_conflict
    reviewer: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    run: Mapped[PipelineRun] = relationship(back_populates="resolutions")


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    evidence_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # content-hash based
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # source_code|config|llm_trace|conflict_record
    file_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_inline: Mapped[str | None] = mapped_column(Text, nullable=True)
    produced_by_node: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LlmTrace(Base):
    __tablename__ = "llm_traces"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evidence_id: Mapped[str | None] = mapped_column(ForeignKey(f"{SCHEMA}.evidence_records.evidence_id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(16), nullable=False)
    prompt_ref: Mapped[str] = mapped_column(Text, nullable=False)
    response_ref: Mapped[str] = mapped_column(Text, nullable=False)
    model_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConflictRecord(Base):
    __tablename__ = "conflict_records"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    conflict_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(512), nullable=False)
    claim_a_domain: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_a_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.evidence_records.evidence_id"), nullable=True
    )
    claim_a_confidence: Mapped[float] = mapped_column(nullable=False)
    claim_b_domain: Mapped[str] = mapped_column(String(16), nullable=False)
    claim_b_evidence_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{SCHEMA}.evidence_records.evidence_id"), nullable=True
    )
    claim_b_confidence: Mapped[float] = mapped_column(nullable=False)
    conflict_type: Mapped[str] = mapped_column(String(32), nullable=False)  # purpose_mismatch|dead_vs_active|value_mismatch
    resolution_policy: Mapped[str | None] = mapped_column(String(48), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)  # auto_resolved|unresolved_written_both
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ParseFailure(Base):
    __tablename__ = "parse_failures"
    __table_args__ = {"schema": SCHEMA}  # noqa: RUF012

    failure_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    language_detected: Mapped[str | None] = mapped_column(String(32), nullable=True)
    parser_attempted: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

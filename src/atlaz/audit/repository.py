"""Audit-write helpers, called from `orchestration.runner`/`orchestration.
nodes` at the points that matter: a run's lifecycle transitions, each HITL
resolution, and (new, LLD Section 14.4) every evidence citation, LLM trace,
cross-domain conflict, and parse failure the pipeline produces. Every
function swallows its own database errors (logged, not raised) -- an
audit-log outage must never be the reason an ingestion run fails; the
pipeline's own checkpoint remains the source of truth for correctness;
these tables are a queryable record on top of it.
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from atlaz.audit.db import session_scope
from atlaz.audit.models import (
    ConflictRecord,
    EvidenceRecord,
    HitlResolution,
    LlmTrace,
    ParseFailure,
    PipelineRun,
)
from atlaz.hitl.models import ReviewResolution
from atlaz.shared.config import DatabaseConfig

# `dict`, not `atlaz.orchestration.capability_registry.CapabilitySnapshot`:
# importing that module here would create `orchestration -> nodes ->
# audit.repository -> orchestration` (this module is imported by
# `orchestration.nodes`, and `atlaz.orchestration`'s package `__init__`
# eagerly imports `graph`/`nodes`) -- a plain `dict` carries the exact same
# shape (`CapabilitySnapshot` is itself just a `TypedDict`) without the cycle.

logger = logging.getLogger(__name__)


def record_run_started(
    thread_id: str,
    repo_path: str,
    hitl_enabled: bool,
    config: DatabaseConfig | None = None,
    *,
    repo_id: str = "",
    run_mode: str = "full",
    capability_registry_snapshot: dict | None = None,
) -> None:
    try:
        with session_scope(config) as session:
            existing = session.get(PipelineRun, thread_id)
            if existing is not None:
                return  # a resume of an already-audited run; nothing new to record
            session.add(
                PipelineRun(
                    thread_id=thread_id,
                    repo_id=repo_id,
                    repo_path=repo_path,
                    run_mode=run_mode,
                    hitl_enabled=hitl_enabled,
                    status="running",
                    capability_registry_snapshot=dict(capability_registry_snapshot) if capability_registry_snapshot else None,
                )
            )
    except Exception:
        logger.warning("Audit log unavailable; continuing without recording run start for %s", thread_id, exc_info=True)


def record_run_status(
    thread_id: str,
    status: str,
    nodes_written: int | None = None,
    edges_written: int | None = None,
    error: str | None = None,
    config: DatabaseConfig | None = None,
) -> None:
    try:
        with session_scope(config) as session:
            run = session.get(PipelineRun, thread_id)
            if run is None:
                return
            run.status = status
            if nodes_written is not None:
                run.nodes_written = nodes_written
            if edges_written is not None:
                run.edges_written = edges_written
            if error is not None:
                run.error = error
    except Exception:
        logger.warning("Audit log unavailable; continuing without recording run status for %s", thread_id, exc_info=True)


def get_run(thread_id: str, config: DatabaseConfig | None = None) -> PipelineRun | None:
    """Read-only lookup, e.g. so the enhancement flow can resolve a run's
    `repo_path` on disk. Unlike the record_* helpers above this does NOT
    swallow a database outage: a caller needing `repo_path` to proceed must
    see that failure, not silently get None and misreport "run not found"."""
    with session_scope(config) as session:
        return session.get(PipelineRun, thread_id)


def list_completed_runs(limit: int = 50, config: DatabaseConfig | None = None) -> list[PipelineRun]:
    """Read-only, like `get_run` -- does NOT swallow a database outage: a
    caller populating a project picker must see that failure and say so,
    not silently show an empty "no projects yet" list that looks like a
    true absence of ingested projects."""
    with session_scope(config) as session:
        stmt = select(PipelineRun).where(PipelineRun.status == "complete").order_by(PipelineRun.started_at.desc()).limit(limit)
        return list(session.scalars(stmt).all())


def record_resolutions(thread_id: str, resolutions: list[ReviewResolution], config: DatabaseConfig | None = None) -> None:
    try:
        with session_scope(config) as session:
            for resolution in resolutions:
                session.add(
                    HitlResolution(
                        thread_id=thread_id,
                        item_id=resolution.item_id,
                        action=resolution.action.value,
                        reviewer=resolution.reviewer,
                        note=resolution.resolution_note,
                    )
                )
    except Exception:
        logger.warning("Audit log unavailable; continuing without recording resolutions for %s", thread_id, exc_info=True)


def record_evidence(records: list[EvidenceRecord], config: DatabaseConfig | None = None) -> None:
    if not records:
        return
    try:
        with session_scope(config) as session:
            for record in records:
                session.merge(record)
    except Exception:
        logger.warning("Audit log unavailable; continuing without recording %d evidence record(s)", len(records), exc_info=True)


def record_llm_traces(traces: list[LlmTrace], config: DatabaseConfig | None = None) -> None:
    if not traces:
        return
    try:
        with session_scope(config) as session:
            for trace in traces:
                session.merge(trace)
    except Exception:
        logger.warning("Audit log unavailable; continuing without recording %d LLM trace(s)", len(traces), exc_info=True)


def record_conflicts(records: list[ConflictRecord], config: DatabaseConfig | None = None) -> None:
    if not records:
        return
    try:
        with session_scope(config) as session:
            for record in records:
                session.merge(record)
    except Exception:
        logger.warning("Audit log unavailable; continuing without recording %d conflict record(s)", len(records), exc_info=True)


def record_parse_failures(failures: list[ParseFailure], config: DatabaseConfig | None = None) -> None:
    if not failures:
        return
    try:
        with session_scope(config) as session:
            for failure in failures:
                session.merge(failure)
    except Exception:
        logger.warning("Audit log unavailable; continuing without recording %d parse failure(s)", len(failures), exc_info=True)

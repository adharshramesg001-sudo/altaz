"""Convenience entry points over the compiled graph: start a run, and resume
one that paused at the HITL gate. `resume_pipeline` is what the Streamlit
review app (a separate process, LLD Section 10.2) calls after a reviewer
submits their resolutions -- it reopens the same checkpoint file by
`thread_id` and hands the graph its `Command(resume=...)`.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langgraph.types import Command

from atlaz.audit.repository import record_resolutions, record_run_started, record_run_status
from atlaz.hitl.models import ReviewItem, ReviewResolution
from atlaz.llm.client import BaseLLMClient
from atlaz.orchestration.capability_registry import load_capability_registry, to_snapshot
from atlaz.orchestration.graph import compile_graph
from atlaz.shared.config import PipelineConfig

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineRunResult:
    thread_id: str
    status: str  # "complete" | "pending_review"
    state: dict[str, Any]
    pending_items: list[ReviewItem] | None = None


def run_pipeline(
    repo_path: str,
    config: PipelineConfig,
    llm_client: BaseLLMClient | None = None,
    thread_id: str | None = None,
    writer_factory=None,
    run_mode: str = "full",
    changed_files: list[str] | None = None,
) -> PipelineRunResult:
    thread_id = thread_id or str(uuid.uuid4())
    logger.info("run_pipeline starting: thread_id=%s repo_path=%s run_mode=%s", thread_id, repo_path, run_mode)

    app = compile_graph(config, llm_client, writer_factory=writer_factory)
    registry = load_capability_registry(config.capability_registry_path)
    record_run_started(
        thread_id,
        repo_path,
        config.hitl_enabled,
        config.database,
        repo_id=Path(repo_path).name,
        run_mode=run_mode,
        capability_registry_snapshot=to_snapshot(registry),
    )

    run_config = {"configurable": {"thread_id": thread_id}}
    initial_state = {"run_id": thread_id, "repo_path": repo_path, "run_mode": run_mode, "changed_files": changed_files}
    try:
        result = app.invoke(initial_state, config=run_config)
    except Exception as exc:
        logger.exception("run_pipeline failed: thread_id=%s repo_path=%s", thread_id, repo_path)
        record_run_status(thread_id, "failed", error=str(exc), config=config.database)
        raise

    run_result = _to_run_result(thread_id, result)
    logger.info("run_pipeline finished: thread_id=%s status=%s", thread_id, run_result.status)
    _audit_run_result(run_result, config)
    return run_result


def resume_pipeline(
    thread_id: str,
    resolutions: list[ReviewResolution],
    config: PipelineConfig,
    llm_client: BaseLLMClient | None = None,
    writer_factory=None,
) -> PipelineRunResult:
    logger.info("resume_pipeline starting: thread_id=%s resolutions=%d", thread_id, len(resolutions))
    app = compile_graph(config, llm_client, writer_factory=writer_factory)
    run_config = {"configurable": {"thread_id": thread_id}}
    try:
        result = app.invoke(Command(resume=resolutions), config=run_config)
    except Exception as exc:
        logger.exception("resume_pipeline failed: thread_id=%s", thread_id)
        record_run_status(thread_id, "failed", error=str(exc), config=config.database)
        raise

    run_result = _to_run_result(thread_id, result)
    logger.info("resume_pipeline finished: thread_id=%s status=%s", thread_id, run_result.status)
    _audit_run_result(run_result, config)
    return run_result


def _audit_run_result(run_result: PipelineRunResult, config: PipelineConfig) -> None:
    """Reads `hitl_resolutions` back out of the final state rather than
    taking a `resolutions` argument directly: that single read covers both
    ways a resolution can happen -- an explicit `resume_pipeline()` call,
    and HITL disabled, where auto-resolve runs inline inside the same
    `run_pipeline()` call and never goes through `resume_pipeline` at all."""
    resolutions = run_result.state.get("hitl_resolutions") or []
    if resolutions:
        record_resolutions(run_result.thread_id, resolutions, config.database)

    if run_result.status == "complete":
        record_run_status(
            run_result.thread_id,
            "complete",
            nodes_written=len(run_result.state.get("graph_write_nodes", [])),
            edges_written=len(run_result.state.get("graph_write_edges", [])),
            config=config.database,
        )
    else:
        record_run_status(run_result.thread_id, "pending_review", config=config.database)


def get_pending_review_items(thread_id: str, config: PipelineConfig, llm_client: BaseLLMClient | None = None) -> list[ReviewItem]:
    """Read the interrupted state directly (no invoke) -- used by the
    Streamlit app to render the queue without re-running any node."""
    app = compile_graph(config, llm_client)
    run_config = {"configurable": {"thread_id": thread_id}}
    return app.get_state(run_config).values.get("flagged_for_review", [])


@dataclass(slots=True)
class RunStatus:
    status: str  # "not_found" | "running" | "pending_review" | "complete"
    nodes_written: int | None = None
    edges_written: int | None = None
    flagged_items: list[ReviewItem] | None = None


def get_run_status(thread_id: str, config: PipelineConfig, llm_client: BaseLLMClient | None = None) -> RunStatus:
    """Reads the LangGraph checkpoint directly rather than a Celery task
    result: the checkpoint is the single source of truth for pipeline state
    (it's also what the Streamlit review app and `resume_pipeline` read/act
    on), and `run_pipeline()`/the Celery task both return successfully
    whether the run completed or merely paused for review -- only the
    checkpoint's own `next`/`tasks` distinguish the two.

    - No checkpoint recorded yet for this `thread_id` -> "not_found" (either
      never started, or a Celery task is running but hasn't reached its
      first checkpoint write yet).
    - `next` non-empty with a pending interrupt -> "pending_review".
    - `next` non-empty, no pending interrupt -> "running".
    - `next` empty (graph reached END) -> "complete".
    """
    app = compile_graph(config, llm_client)
    run_config = {"configurable": {"thread_id": thread_id}}
    snapshot = app.get_state(run_config)

    if not snapshot.values:
        return RunStatus(status="not_found")

    if not snapshot.next:
        return RunStatus(
            status="complete",
            nodes_written=len(snapshot.values.get("graph_write_nodes", [])),
            edges_written=len(snapshot.values.get("graph_write_edges", [])),
        )

    pending_interrupt = any(task.interrupts for task in snapshot.tasks)
    if pending_interrupt:
        return RunStatus(status="pending_review", flagged_items=snapshot.values.get("flagged_for_review", []))

    return RunStatus(status="running")


def _to_run_result(thread_id: str, result: dict) -> PipelineRunResult:
    interrupts = result.get("__interrupt__")
    if interrupts:
        pending_items = interrupts[0].value
        return PipelineRunResult(thread_id=thread_id, status="pending_review", state=result, pending_items=pending_items)
    return PipelineRunResult(thread_id=thread_id, status="complete", state=result)

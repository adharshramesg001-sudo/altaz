"""Convenience entry points over the compiled graph: start a run, and resume
one that paused at the HITL gate. `resume_pipeline` is what the Streamlit
review app (a separate process, LLD Section 10.2) calls after a reviewer
submits their resolutions -- it reopens the same checkpoint file by
`thread_id` and hands the graph its `Command(resume=...)`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from langgraph.types import Command

from atlaz.hitl.models import ReviewItem, ReviewResolution
from atlaz.llm.client import BaseLLMClient
from atlaz.orchestration.graph import compile_graph
from atlaz.shared.config import PipelineConfig


@dataclass(slots=True)
class PipelineRunResult:
    thread_id: str
    status: str  # "complete" | "pending_review"
    state: dict[str, Any]
    pending_items: list[ReviewItem] | None = None


def run_pipeline(
    repo_path: str, config: PipelineConfig, llm_client: BaseLLMClient | None = None, thread_id: str | None = None
) -> PipelineRunResult:
    thread_id = thread_id or str(uuid.uuid4())
    app = compile_graph(config, llm_client)
    run_config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke({"repo_path": repo_path}, config=run_config)
    return _to_run_result(thread_id, result)


def resume_pipeline(
    thread_id: str,
    resolutions: list[ReviewResolution],
    config: PipelineConfig,
    llm_client: BaseLLMClient | None = None,
) -> PipelineRunResult:
    app = compile_graph(config, llm_client)
    run_config = {"configurable": {"thread_id": thread_id}}
    result = app.invoke(Command(resume=resolutions), config=run_config)
    return _to_run_result(thread_id, result)


def get_pending_review_items(thread_id: str, config: PipelineConfig, llm_client: BaseLLMClient | None = None) -> list[ReviewItem]:
    """Read the interrupted state directly (no invoke) -- used by the
    Streamlit app to render the queue without re-running any node."""
    app = compile_graph(config, llm_client)
    run_config = {"configurable": {"thread_id": thread_id}}
    return app.get_state(run_config).values.get("flagged_for_review", [])


def _to_run_result(thread_id: str, result: dict) -> PipelineRunResult:
    interrupts = result.get("__interrupt__")
    if interrupts:
        pending_items = interrupts[0].value
        return PipelineRunResult(thread_id=thread_id, status="pending_review", state=result, pending_items=pending_items)
    return PipelineRunResult(thread_id=thread_id, status="complete", state=result)

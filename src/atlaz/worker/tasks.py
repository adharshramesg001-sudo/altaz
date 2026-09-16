"""Celery task wrapping the ingestion pipeline.

Deliberately returns a small JSON-safe summary dict, not the full
`PipelineRunResult` (which carries live dataclass instances that don't
round-trip through Celery's JSON result serializer). `GET /runs/{thread_id}`
doesn't actually read this task result for the interesting bits anyway --
it reads the LangGraph checkpoint directly via `get_run_status`, since that
checkpoint (not the Celery result backend) is the single source of truth
for pipeline state, and is what distinguishes "complete" from
"pending_review" (both of which are simply a successful task return here).
"""

from __future__ import annotations

import logging

from atlaz.orchestration.runner import run_pipeline
from atlaz.shared.config import PipelineConfig
from atlaz.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="atlaz.run_ingestion", bind=True)
def run_ingestion_task(
    self, repo_path: str, thread_id: str, hitl_enabled: bool | None = None
) -> dict:
    config = PipelineConfig.from_env()
    if hitl_enabled is not None:
        config.hitl_enabled = hitl_enabled

    logger.info(
        "Ingestion task started: thread_id=%s repo_path=%s hitl_enabled=%s llm_provider=%s llm_model=%s",
        thread_id, repo_path, config.hitl_enabled, config.llm.provider, config.llm.model,
    )
    try:
        result = run_pipeline(repo_path, config, thread_id=thread_id)
    except Exception:
        logger.exception("Ingestion task failed: thread_id=%s repo_path=%s", thread_id, repo_path)
        raise

    logger.info("Ingestion task finished: thread_id=%s status=%s", thread_id, result.status)

    return {
        "thread_id": result.thread_id,
        "status": result.status,
        "nodes_written": len(result.state.get("graph_write_nodes", [])) if result.status == "complete" else None,
        "edges_written": len(result.state.get("graph_write_edges", [])) if result.status == "complete" else None,
        "flagged_count": len(result.pending_items or []) if result.status == "pending_review" else None,
    }

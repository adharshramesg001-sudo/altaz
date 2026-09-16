"""FastAPI ingestion API.

Run with:
    uvicorn atlaz.api.main:app --host 0.0.0.0 --port 8000

Starting a run requires a Celery worker to actually be consuming the queue
(`celery -A atlaz.worker.celery_app.celery_app worker --loglevel=info`) --
`POST /ingest` only enqueues the job and returns immediately (LLD-adjacent:
ingestion can run several agents' worth of LLM calls, so blocking an HTTP
request for the whole run is the wrong shape).

`GET /runs/{thread_id}` and `POST /runs/{thread_id}/resolve` both read the
LangGraph checkpoint directly (via `atlaz.orchestration.runner`), not the
Celery result backend -- the checkpoint is the single source of truth for
where a run actually is, and it's what the Streamlit review app already
uses (LLD Section 10.2).
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from celery.result import AsyncResult
from fastapi import FastAPI, HTTPException

from atlaz.api.resolution_builder import build_resolutions
from atlaz.api.schemas import (
    FlaggedItemSummary,
    GenerateDocsRequest,
    GenerateDocsResponse,
    IngestRequest,
    IngestResponse,
    ResolveRunRequest,
    RunStatusResponse,
)
from atlaz.llm.client import build_llm_client
from atlaz.orchestration.runner import RunStatus, get_pending_review_items, get_run_status, resume_pipeline
from atlaz.reasoning.neo4j_query_runner import Neo4jReasoningStore
from atlaz.shared.config import PipelineConfig
from atlaz.shared.logging_config import configure_logging
from atlaz.worker.celery_app import celery_app
from atlaz.worker.tasks import run_ingestion_task

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="AtlaZ Ingestion API", version="0.1.0")


@app.post("/ingest", response_model=IngestResponse, status_code=202)
def start_ingest(req: IngestRequest) -> IngestResponse:
    if not Path(req.repo_path).is_dir():
        logger.warning("Rejected /ingest: repo_path does not exist: %s", req.repo_path)
        raise HTTPException(422, f"repo_path does not exist or is not a directory: {req.repo_path}")

    thread_id = req.thread_id or str(uuid.uuid4())
    logger.info(
        "POST /ingest -> enqueued thread_id=%s repo_path=%s hitl_enabled=%s",
        thread_id, req.repo_path, req.hitl_enabled,
    )
    run_ingestion_task.apply_async(
        kwargs={"repo_path": req.repo_path, "thread_id": thread_id, "hitl_enabled": req.hitl_enabled},
        task_id=thread_id,
    )
    return IngestResponse(thread_id=thread_id, status="queued")


@app.get("/runs/{thread_id}", response_model=RunStatusResponse)
def run_status(thread_id: str) -> RunStatusResponse:
    celery_state = AsyncResult(thread_id, app=celery_app).state
    if celery_state == "FAILURE":
        error = AsyncResult(thread_id, app=celery_app).result
        logger.error("GET /runs/%s -> celery task failed: %s", thread_id, error)
        return RunStatusResponse(thread_id=thread_id, status="failed", error=str(error))

    config = PipelineConfig.from_env()
    status = get_run_status(thread_id, config)
    logger.info("GET /runs/%s -> status=%s", thread_id, status.status)
    return _to_response(thread_id, status)


@app.post("/runs/{thread_id}/resolve", response_model=RunStatusResponse)
def resolve_run(thread_id: str, req: ResolveRunRequest) -> RunStatusResponse:
    config = PipelineConfig.from_env()
    flagged = get_pending_review_items(thread_id, config)
    if not flagged:
        logger.warning("POST /runs/%s/resolve -> no pending review items", thread_id)
        raise HTTPException(404, f"no pending review items for thread_id={thread_id}")

    logger.info(
        "POST /runs/%s/resolve -> applying %d resolution(s) to %d flagged item(s)",
        thread_id, len(req.resolutions), len(flagged),
    )
    resolutions = build_resolutions(flagged, req.resolutions)
    result = resume_pipeline(thread_id, resolutions, config)
    status = get_run_status(result.thread_id, config)
    logger.info("POST /runs/%s/resolve -> status=%s", thread_id, status.status)
    return _to_response(result.thread_id, status)


@app.post("/runs/{thread_id}/documents", response_model=GenerateDocsResponse)
def generate_documents(thread_id: str, req: GenerateDocsRequest) -> GenerateDocsResponse:
    from atlaz.docgen.service import DocumentationService

    config = PipelineConfig.from_env()
    llm_client = build_llm_client(config.llm)

    logger.info("POST /runs/%s/documents -> project_id=%s save=%s", thread_id, req.project_id, req.save)
    with Neo4jReasoningStore(config.neo4j) as store:
        service = DocumentationService(llm_client, store.run, output_root="outputs")
        try:
            result = service.run(thread_id, req.project_id, save=req.save)
        except ValueError as exc:
            logger.warning("POST /runs/%s/documents -> %s", thread_id, exc)
            raise HTTPException(404, str(exc)) from exc

    hld_path = str(result.output_dir / "HLD.md") if result.output_dir else None
    lld_path = str(result.output_dir / "LLD.md") if result.output_dir else None
    logger.info("POST /runs/%s/documents -> saved to %s", thread_id, result.output_dir)
    return GenerateDocsResponse(
        thread_id=thread_id, project_id=req.project_id, hld_path=hld_path, lld_path=lld_path,
        hld_markdown=result.hld_markdown, lld_markdown=result.lld_markdown,
    )


def _to_response(thread_id: str, status: RunStatus) -> RunStatusResponse:
    flagged_items = None
    if status.flagged_items is not None:
        flagged_items = [
            FlaggedItemSummary(
                item_id=item.item_id,
                kind=item.kind.value,
                source_domain=item.source_domain,
                summary=item.summary,
                confidence=item.confidence,
            )
            for item in status.flagged_items
        ]
    return RunStatusResponse(
        thread_id=thread_id,
        status=status.status,
        nodes_written=status.nodes_written,
        edges_written=status.edges_written,
        flagged_items=flagged_items,
    )

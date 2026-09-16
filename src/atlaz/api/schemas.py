"""Pydantic request/response models for the FastAPI ingestion API.

Resolutions arrive over HTTP as small, JSON-safe choices (`accept` /
`reject`, plus a free-text `answer` for gap confirmations) rather than a
serialized `ReviewResolution` -- a `ReviewResolution.resolved_value` is
often an arbitrary project dataclass (a `CapabilityCluster`, ...), which a
generic HTTP client has no way to construct. The API looks the real object
up server-side from the freshly-read flagged-item queue and builds the
actual `ReviewResolution` itself -- see `atlaz.api.resolution_builder`.
Cross-domain conflicts are resolved automatically by
`atlaz.orchestration.dispute_resolution`, not through this HTTP flow (see
`atlaz.hitl.models`'s module docstring). A client that needs to *edit* a
finding's content (not just accept/reject it) uses the Streamlit review
app, which works with the objects directly in-process.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class IngestRequest(BaseModel):
    repo_path: str
    thread_id: str | None = None
    hitl_enabled: bool | None = None  # None = use the server's configured default


class IngestResponse(BaseModel):
    thread_id: str
    status: Literal["queued"]


class FlaggedItemSummary(BaseModel):
    item_id: str
    kind: str
    source_domain: str
    summary: str
    confidence: float | None = None


class RunStatusResponse(BaseModel):
    thread_id: str
    status: Literal["not_found", "running", "pending_review", "complete", "failed"]
    nodes_written: int | None = None
    edges_written: int | None = None
    flagged_items: list[FlaggedItemSummary] | None = None
    error: str | None = None


class ResolutionRequest(BaseModel):
    item_id: str
    action: Literal["accept", "reject"]
    answer: str | None = Field(
        default=None, description="Gap-confirmation free-text answer (only used when action='accept')."
    )
    reviewer: str = ""
    note: str = ""


class ResolveRunRequest(BaseModel):
    resolutions: list[ResolutionRequest]


class GenerateDocsRequest(BaseModel):
    project_id: str = Field(description="Groups this document set under outputs/<project_id>/docs/<timestamp>/")
    save: bool = True


class GenerateDocsResponse(BaseModel):
    thread_id: str
    project_id: str
    hld_path: str | None = None
    lld_path: str | None = None
    hld_markdown: str
    lld_markdown: str

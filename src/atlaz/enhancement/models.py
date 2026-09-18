"""Dataclasses for the enhancement/retrieval flow (impact analysis,
guideline retrieval, generated file content). Kept separate from
`atlaz.orchestration.state.PipelineState` because this flow runs against an
already-ingested repo's knowledge graph, not as a stage of the extraction
pipeline itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ImpactedFile:
    file_path: str
    reason: str
    matched_node_labels: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ImpactAnalysisResult:
    matched_nodes: list[str]
    files: list[ImpactedFile]
    graph_context: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class RetrievedGuideline:
    title: str
    category: str
    content: str
    score: float


@dataclass(slots=True)
class FileModification:
    file_path: str
    original_content: str
    modified_content: str
    task_description: str


@dataclass(slots=True)
class ModificationTask:
    file_path: str
    title: str
    description: str


@dataclass(slots=True)
class ModificationPlan:
    summary: str
    tasks: list[ModificationTask] = field(default_factory=list)


@dataclass(slots=True)
class FileValidation:
    file_path: str
    syntax_valid: bool = True
    warnings: list[str] = field(default_factory=list)
    security_issues: list[str] = field(default_factory=list)

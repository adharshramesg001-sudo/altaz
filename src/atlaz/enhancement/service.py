"""Orchestrates one enhancement request end to end against an already
ingested run: resolve the run's `repo_path` -> impact analysis over the
knowledge graph -> guideline retrieval -> modernization planning -> per-file
code modification -> deterministic validation -> (on request) write results
to `outputs/`.

Deliberately not a LangGraph state graph like the ingestion pipeline in
`atlaz.orchestration`: this flow is a single linear pass with no HITL
interrupt/resume semantics, so a handful of injected collaborators
(mirroring every other agent's DI shape in this codebase) is simpler than a
second checkpointed graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from atlaz.audit.repository import get_run
from atlaz.enhancement.guideline_store import GuidelineRetrievalAgent
from atlaz.enhancement.impact_analysis import ImpactAnalysisAgent
from atlaz.enhancement.models import (
    FileModification,
    FileValidation,
    ImpactAnalysisResult,
    ModificationPlan,
    RetrievedGuideline,
)
from atlaz.enhancement.modifier import CodeModificationAgent
from atlaz.enhancement.output_writer import write_modifications
from atlaz.enhancement.planner import PlanningAgent
from atlaz.enhancement.validator import ValidationAgent
from atlaz.shared.config import DatabaseConfig


@dataclass(slots=True)
class EnhancementResult:
    thread_id: str
    repo_path: str
    impact: ImpactAnalysisResult
    guidelines: list[RetrievedGuideline]
    modifications: list[FileModification]
    plan: ModificationPlan | None = None
    validations: list[FileValidation] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    output_dir: Path | None = None


class EnhancementService:
    def __init__(
        self,
        impact_agent: ImpactAnalysisAgent,
        modifier: CodeModificationAgent,
        guideline_agent: GuidelineRetrievalAgent | None = None,
        planning_agent: PlanningAgent | None = None,
        validation_agent: ValidationAgent | None = None,
        output_root: Path | str = "outputs",
        database_config: DatabaseConfig | None = None,
    ) -> None:
        self.impact_agent = impact_agent
        self.modifier = modifier
        self.guideline_agent = guideline_agent
        self.planning_agent = planning_agent
        self.validation_agent = validation_agent or ValidationAgent()
        self.output_root = output_root
        self.database_config = database_config

    def resolve_repo_path(self, thread_id: str) -> str:
        run = get_run(thread_id, self.database_config)
        if run is None:
            raise ValueError(f"No ingestion run found for thread_id={thread_id!r}")
        return run.repo_path

    def analyze(
        self, thread_id: str, enhancement_request: str
    ) -> tuple[str, ImpactAnalysisResult, list[RetrievedGuideline]]:
        repo_path = self.resolve_repo_path(thread_id)
        impact = self.impact_agent.run(enhancement_request)
        guidelines = self.guideline_agent.query(enhancement_request) if self.guideline_agent else []
        return repo_path, impact, guidelines

    def plan(
        self,
        enhancement_request: str,
        impact: ImpactAnalysisResult,
        guidelines: list[RetrievedGuideline],
    ) -> ModificationPlan | None:
        if self.planning_agent is None:
            return None
        return self.planning_agent.run(enhancement_request, impact, guidelines)

    def generate(
        self,
        repo_path: str,
        enhancement_request: str,
        impact: ImpactAnalysisResult,
        guidelines: list[RetrievedGuideline],
        plan: ModificationPlan | None = None,
    ) -> tuple[list[FileModification], list[str]]:
        task_by_file = {task.file_path: task for task in (plan.tasks if plan else [])}
        modifications: list[FileModification] = []
        skipped: list[str] = []
        for impacted in impact.files:
            full_path = Path(repo_path) / impacted.file_path
            if not full_path.is_file():
                skipped.append(impacted.file_path)
                continue
            content = full_path.read_text(encoding="utf-8", errors="ignore")
            task = task_by_file.get(impacted.file_path)
            if task:
                task_description = f"{task.title}\n\n{task.description}\n\n(Relevance: {impacted.reason})"
            else:
                task_description = f"{enhancement_request}\n\n(Relevance: {impacted.reason})"
            modifications.append(self.modifier.run(impacted.file_path, content, task_description, guidelines))
        return modifications, skipped

    def validate(self, modifications: list[FileModification]) -> list[FileValidation]:
        return self.validation_agent.run(modifications)

    def run(self, thread_id: str, enhancement_request: str) -> EnhancementResult:
        repo_path, impact, guidelines = self.analyze(thread_id, enhancement_request)
        plan = self.plan(enhancement_request, impact, guidelines)
        modifications, skipped = self.generate(repo_path, enhancement_request, impact, guidelines, plan)
        validations = self.validate(modifications)
        return EnhancementResult(
            thread_id=thread_id,
            repo_path=repo_path,
            impact=impact,
            guidelines=guidelines,
            modifications=modifications,
            plan=plan,
            validations=validations,
            skipped_files=skipped,
        )

    def save(self, result: EnhancementResult, enhancement_request: str) -> Path:
        output_dir = write_modifications(
            self.output_root,
            result.thread_id,
            enhancement_request,
            result.impact,
            result.guidelines,
            result.modifications,
            result.plan,
            result.validations,
        )
        result.output_dir = output_dir
        return output_dir

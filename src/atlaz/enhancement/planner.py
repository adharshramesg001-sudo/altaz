"""Produces a human-readable modernization plan before any file is touched --
one LLM call, JSON-structured, that explains *why* each impacted file matters
and what should change in it. Mirrors Brownfield's `PlannerAgent` (plan
before modify), reimplemented against `BaseLLMClient.complete_json` rather
than a hardcoded Azure OpenAI JSON-mode call.

Purely additive to the flow: `EnhancementService.generate()` still modifies
every file impact analysis found regardless of what the plan says, using a
task's title/description to sharpen the prompt when one matches a file and
falling back to the generic request text otherwise. So a provider that
returns no usable JSON (e.g. `MockLLMClient`, whose schema-mock always
returns an empty list for an "array" field) degrades to the pre-planning
behavior rather than silently dropping files.
"""

from __future__ import annotations

from atlaz.enhancement.models import (
    ImpactAnalysisResult,
    ModificationPlan,
    ModificationTask,
    RetrievedGuideline,
)
from atlaz.llm.client import BaseLLMClient

_INSTRUCTIONS = (
    "You are a principal software architect planning a code modernization change for an "
    "existing codebase. Given the enhancement request, the files the knowledge graph says "
    "are impacted, and any enterprise guidelines, respond with a JSON object with two fields:\n"
    "1. 'summary': a markdown-formatted rationale (a few short paragraphs or a bullet list) "
    "explaining what will change and why, citing which guidelines apply where relevant.\n"
    "2. 'tasks': one entry per file that genuinely needs a code change, each with 'file_path' "
    "(must exactly match one of the impacted files listed below), 'title' (a short phrase), "
    "and 'description' (specific instructions for that file). Omit files that are impacted "
    "contextually but don't need edits."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        },
    },
}

_NO_PLAN_SUMMARY = "_No plan summary was generated._"


class PlanningAgent:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        enhancement_request: str,
        impact: ImpactAnalysisResult,
        guidelines: list[RetrievedGuideline] | None = None,
    ) -> ModificationPlan:
        guideline_text = "\n".join(f"- [{g.category}] {g.title}: {g.content}" for g in guidelines or [])
        files_text = "\n".join(f"- {f.file_path} — {f.reason}" for f in impact.files) or "(none found)"
        prompt = (
            f"{_INSTRUCTIONS}\n\n"
            f"ENHANCEMENT REQUEST:\n{enhancement_request}\n\n"
            f"IMPACTED FILES (from the knowledge graph):\n{files_text}\n\n"
            f"ENTERPRISE GUIDELINES:\n{guideline_text or '(none retrieved)'}\n"
        )
        data = self.llm_client.complete_json(prompt, schema=_SCHEMA)

        known_paths = {f.file_path for f in impact.files}
        tasks = [
            ModificationTask(
                file_path=raw_task["file_path"],
                title=str(raw_task.get("title", "")),
                description=str(raw_task.get("description", "")),
            )
            for raw_task in data.get("tasks", [])
            if isinstance(raw_task, dict) and raw_task.get("file_path") in known_paths
        ]
        summary = str(data.get("summary") or "").strip() or _NO_PLAN_SUMMARY
        return ModificationPlan(summary=summary, tasks=tasks)

"""Produces a migration plan across every unit before any code is
generated -- one LLM call, JSON-structured, mirroring
`atlaz.enhancement.planner.PlanningAgent`'s shape but scoped to migration
units (capabilities/services) built from the whole knowledge graph, and to
a free-form migration request ("migrate this to FastAPI microservices")
rather than a narrow enhancement request.
"""

from __future__ import annotations

from atlaz.llm.client import BaseLLMClient
from atlaz.migration.models import MigrationPlan, MigrationTask, MigrationUnit

_INSTRUCTIONS = (
    "You are a principal software architect planning a full migration of a system to the new "
    "target described in the request below. You have been given the complete knowledge-graph "
    "understanding of the current system, grouped into units (each a business capability or "
    "service), and the project's current primary language. Respond with a JSON object with four "
    "fields:\n"
    "1. 'summary': a markdown-formatted migration plan -- the target architecture, how each unit "
    "maps onto it, and the recommended migration order.\n"
    "2. 'tasks': one entry per unit that needs to be migrated, each with 'unit_id' (must exactly "
    "match one of the units below), 'title', 'description' (specific migration instructions for "
    "that unit), and 'target_files' (proposed file paths for the new stack).\n"
    "3. 'target_language': the single primary language of the target stack this request describes.\n"
    "4. 'same_language': true if the target language is the same as the current primary language "
    "(a framework/library upgrade, e.g. Flask to FastAPI, both Python), false if this is a "
    "migration to a genuinely different language."
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
                    "unit_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "target_files": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "target_language": {"type": "string"},
        "same_language": {"type": "boolean"},
    },
}

_NO_PLAN_SUMMARY = "_No migration plan was generated._"


class MigrationPlanningAgent:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(self, migration_request: str, units: list[MigrationUnit], current_language: str = "") -> MigrationPlan:
        units_text = "\n\n".join(f"### {u.unit_id} ({u.unit_type}: {u.name})\n{u.description}" for u in units)
        prompt = (
            f"{_INSTRUCTIONS}\n\n"
            f"MIGRATION REQUEST:\n{migration_request}\n\n"
            f"CURRENT PRIMARY LANGUAGE: {current_language or '(unknown)'}\n\n"
            f"CURRENT SYSTEM (from the knowledge graph):\n{units_text or '(no units found)'}\n"
        )
        data = self.llm_client.complete_json(prompt, schema=_SCHEMA)

        known_ids = {u.unit_id for u in units}
        tasks = [
            MigrationTask(
                unit_id=raw["unit_id"],
                title=str(raw.get("title", "")),
                description=str(raw.get("description", "")),
                target_files=[str(f) for f in raw.get("target_files", []) if isinstance(f, str)],
            )
            for raw in data.get("tasks", [])
            if isinstance(raw, dict) and raw.get("unit_id") in known_ids
        ]
        summary = str(data.get("summary") or "").strip() or _NO_PLAN_SUMMARY
        # A provider that can't reliably classify this (or MockLLMClient's schema-mock, which
        # always returns False for a boolean field) should err toward the safer path: treat an
        # unclear answer as cross-language, which routes dependency mappings through human
        # confirmation rather than letting them flow through unreviewed.
        same_language = bool(data.get("same_language", False))
        target_language = str(data.get("target_language") or "").strip()
        return MigrationPlan(summary=summary, tasks=tasks, target_language=target_language, same_language=same_language)

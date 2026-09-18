"""Generates fresh code for one migration unit's target stack -- grounded
entirely in the unit's graph-derived `description` (files, workflow steps,
business rules, tables, APIs; see `unit_builder.py`), never in the original
file source. This is the "Knowledge Understanding -> Modernized Code" half
of the migration flow, deliberately distinct from
`atlaz.enhancement.modifier.CodeModificationAgent`, which patches existing
file text in place. A unit can produce more than one file, so this returns
structured JSON (`complete_json`) rather than a single raw-text completion.
"""

from __future__ import annotations

from atlaz.enhancement.models import RetrievedGuideline
from atlaz.llm.client import BaseLLMClient
from atlaz.migration.models import GeneratedFile, GeneratedUnit, MigrationUnit

_INSTRUCTIONS = (
    "You are an expert software engineer implementing one unit of a system migration in its new "
    "target stack. You are given only the knowledge-graph understanding of what this unit does "
    "below -- you do not have, and must not assume, the original source code. Rules:\n"
    "1. Implement exactly the behavior described below -- workflows, business rules, data model, "
    "and API contracts -- in the target stack described in the migration request.\n"
    "2. If the understanding below lists response field names for an API, your generated response "
    "for that API MUST contain exactly those field names -- do not rename, drop, or invent fields. "
    "A client of the original API depends on that exact shape; this is a hard external contract, "
    "not a style choice.\n"
    "3. Follow the enterprise guidelines below wherever they apply.\n"
    "4. Respond with a JSON object with one field, 'files': a list of objects, each with "
    "'file_path' (relative, in the new stack's conventional layout) and 'content' (the complete "
    "file contents -- no markdown fences, no commentary)."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
            },
        }
    },
}


class UnitMigrationAgent:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        migration_request: str,
        unit: MigrationUnit,
        task_description: str,
        guidelines: list[RetrievedGuideline] | None = None,
    ) -> GeneratedUnit:
        guideline_text = "\n".join(f"- [{g.category}] {g.title}: {g.content}" for g in guidelines or [])
        prompt = (
            f"{_INSTRUCTIONS}\n\n"
            f"MIGRATION REQUEST:\n{migration_request}\n\n"
            f"UNIT: {unit.name} ({unit.unit_type})\n\n"
            f"TASK:\n{task_description}\n\n"
            "KNOWLEDGE-GRAPH UNDERSTANDING OF THIS UNIT (your only source of truth about current "
            f"behavior):\n{unit.description}\n\n"
            f"ENTERPRISE GUIDELINES:\n{guideline_text or '(none retrieved)'}\n"
        )
        data = self.llm_client.complete_json(prompt, schema=_SCHEMA)
        files = [
            GeneratedFile(file_path=str(raw["file_path"]), content=str(raw.get("content", "")))
            for raw in data.get("files", [])
            if isinstance(raw, dict) and raw.get("file_path")
        ]
        return GeneratedUnit(
            unit_id=unit.unit_id,
            unit_type=unit.unit_type,
            name=unit.name,
            task_description=task_description,
            files=files,
        )

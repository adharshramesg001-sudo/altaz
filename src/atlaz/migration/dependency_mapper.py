"""Proposes a target-ecosystem replacement for each currently-declared
dependency -- one LLM call, JSON-structured. This is inherently the highest-
uncertainty step in the whole migration flow: existence in a registry (see
`dependency_verifier.py`) can be checked deterministically, but whether a
proposed replacement is truly *feature-equivalent* to how this codebase
actually uses the original package cannot be. The caller is expected to
treat `same_language=False` proposals as needing human confirmation before
they're used to ground code generation (`MigrationService`'s webapp caller
does this via a soft, in-page HITL step); `same_language=True` proposals
still get registry-verified, but flow straight through.
"""

from __future__ import annotations

from atlaz.llm.client import BaseLLMClient
from atlaz.migration.models import Dependency, DependencyMapping

_INSTRUCTIONS = (
    "You are a principal software architect proposing dependency replacements for a system "
    "migration. Given the migration request, the current primary language, the target language, "
    "and the list of currently-declared dependencies below, propose a target-ecosystem "
    "replacement for each one. If the target language is the same as the current language, most "
    "dependencies likely carry over unchanged (propose the same name/ecosystem) -- only propose a "
    "replacement where the original package is tied to a framework/library actually being "
    "replaced by the migration. If the target language differs, propose the closest equivalent "
    "package in the target ecosystem's package manager (pip -> pypi, npm -> npm, Go -> go modules, "
    "Java/Kotlin -> Maven, Ruby -> RubyGems, PHP -> Packagist, Rust -> crates.io, C# -> NuGet). "
    "Respond with a JSON object with one field, 'mappings': a list of objects, each with "
    "'current_name' (must exactly match one of the dependencies below), 'target_name', "
    "'target_version' (a plausible version, or empty if unsure), 'target_ecosystem', and "
    "'justification' (one sentence)."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "mappings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "current_name": {"type": "string"},
                    "target_name": {"type": "string"},
                    "target_version": {"type": "string"},
                    "target_ecosystem": {"type": "string"},
                    "justification": {"type": "string"},
                },
            },
        }
    },
}


class DependencyMappingAgent:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        migration_request: str,
        dependencies: list[Dependency],
        target_language: str,
        same_language: bool,
    ) -> list[DependencyMapping]:
        if not dependencies:
            return []

        deps_text = "\n".join(f"- {d.name} {d.version} ({d.ecosystem}, from {d.manifest_path})" for d in dependencies)
        prompt = (
            f"{_INSTRUCTIONS}\n\n"
            f"MIGRATION REQUEST:\n{migration_request}\n\n"
            f"TARGET LANGUAGE: {target_language or '(unspecified -- assume same language)'}\n"
            f"SAME LANGUAGE AS CURRENT: {same_language}\n\n"
            f"CURRENT DEPENDENCIES:\n{deps_text}\n"
        )
        data = self.llm_client.complete_json(prompt, schema=_SCHEMA)

        by_name = {d.name: d for d in dependencies}
        mappings: list[DependencyMapping] = []
        for raw in data.get("mappings", []):
            if not isinstance(raw, dict):
                continue
            current = by_name.get(raw.get("current_name"))
            if current is None:
                continue
            mappings.append(
                DependencyMapping(
                    current_name=current.name,
                    current_version=current.version,
                    current_ecosystem=current.ecosystem,
                    target_name=str(raw.get("target_name") or current.name),
                    target_version=str(raw.get("target_version") or ""),
                    target_ecosystem=str(raw.get("target_ecosystem") or current.ecosystem),
                    justification=str(raw.get("justification") or ""),
                    same_language=same_language,
                )
            )

        # Dependencies the LLM didn't mention (e.g. MockLLMClient's schema-mock always returns []
        # for array fields) still need a mapping -- default to "carries over unchanged, unreviewed."
        mapped_names = {m.current_name for m in mappings}
        for dep in dependencies:
            if dep.name in mapped_names:
                continue
            mappings.append(
                DependencyMapping(
                    current_name=dep.name, current_version=dep.version, current_ecosystem=dep.ecosystem,
                    target_name=dep.name, target_version=dep.version, target_ecosystem=dep.ecosystem,
                    justification="No mapping proposed -- carried over unchanged.", same_language=same_language,
                )
            )
        return mappings

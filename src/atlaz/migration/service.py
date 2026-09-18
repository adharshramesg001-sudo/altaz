"""Orchestrates one full-project migration request end to end: resolve the
run -> pull the whole knowledge graph (`atlaz.docgen.graph_facts.
fetch_project_facts`, the same fact assembly HLD/LLD generation uses) ->
group it into migration units (capabilities, or services/whole-project as
fallbacks, plus an infra unit for Dockerfile/CI/IaC/manifests) -> scan
dependency manifests -> plan the migration (including a same-language vs.
cross-language call) -> propose + registry-verify a dependency mapping ->
generate fresh code per unit (graph-facts-only for capability/service
units, real file content for the infra unit) -> validate (syntax/security
checks, plus a deterministic check that every response field name observed
in the original code is still present in the generated output -- see
`api_response_shape.flag_missing_response_fields`) -> (on request) write to
`outputs/`.

`run()` is the single-shot convenience path (used by the CLI, and by the
webapp for a same-language request): every stage runs automatically, no
pause. For a cross-language request, the webapp instead calls the stages
individually up through `verify_dependency_mappings()`, shows the proposed
mapping for human confirmation (a soft, in-page HITL -- see
`dependency_mapper.py`'s docstring for why cross-language mapping can't be
fully automated), and only then calls `generate()` with the confirmed
mappings. Every stage is a plain method precisely so both callers can share
it without duplicating orchestration logic.

Deliberately separate from `atlaz.enhancement.service.EnhancementService`:
that flow patches a keyword-matched subset of *existing* files; this one
regenerates the system from the graph's understanding of it. Same "linear
pass, injected collaborators, propose-only" shape as every other on-demand
service in this codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from atlaz.audit.models import PipelineRun
from atlaz.audit.repository import get_run
from atlaz.docgen.graph_facts import QueryRunner, fetch_project_facts
from atlaz.enhancement.guideline_store import GuidelineRetrievalAgent
from atlaz.enhancement.models import FileModification, FileValidation, RetrievedGuideline
from atlaz.enhancement.validator import ValidationAgent
from atlaz.migration.api_response_shape import flag_missing_response_fields
from atlaz.migration.dependency_mapper import DependencyMappingAgent
from atlaz.migration.dependency_scanner import scan_dependencies
from atlaz.migration.dependency_verifier import RegistryClient
from atlaz.migration.dependency_verifier import verify_dependency_mappings as run_registry_verification
from atlaz.migration.generator import UnitMigrationAgent
from atlaz.migration.infra_files import fetch_files_by_classification
from atlaz.migration.infra_generator import InfraMigrationAgent
from atlaz.migration.models import Dependency, DependencyMapping, GeneratedUnit, MigrationPlan, MigrationUnit
from atlaz.migration.output_writer import write_migration
from atlaz.migration.planner import MigrationPlanningAgent
from atlaz.migration.unit_builder import build_infra_unit, build_migration_units
from atlaz.shared.config import DatabaseConfig


@dataclass(slots=True)
class MigrationResult:
    thread_id: str
    repo_id: str
    units: list[MigrationUnit]
    plan: MigrationPlan
    guidelines: list[RetrievedGuideline]
    generated_units: list[GeneratedUnit]
    dependencies: list[Dependency] = field(default_factory=list)
    dependency_mappings: list[DependencyMapping] = field(default_factory=list)
    validations: list[FileValidation] = field(default_factory=list)
    output_dir: Path | None = None


class MigrationService:
    def __init__(
        self,
        query_runner: QueryRunner,
        planning_agent: MigrationPlanningAgent,
        generation_agent: UnitMigrationAgent,
        guideline_agent: GuidelineRetrievalAgent | None = None,
        validation_agent: ValidationAgent | None = None,
        infra_generation_agent: InfraMigrationAgent | None = None,
        dependency_mapping_agent: DependencyMappingAgent | None = None,
        registry_client: RegistryClient | None = None,
        output_root: Path | str = "outputs",
        database_config: DatabaseConfig | None = None,
    ) -> None:
        self.query_runner = query_runner
        self.planning_agent = planning_agent
        self.generation_agent = generation_agent
        self.guideline_agent = guideline_agent
        self.validation_agent = validation_agent or ValidationAgent()
        self.infra_generation_agent = infra_generation_agent
        self.dependency_mapping_agent = dependency_mapping_agent
        self.registry_client = registry_client
        self.output_root = output_root
        self.database_config = database_config
        # Set by `gather_units()` as a side effect (it already reads `ProjectFacts`, which is
        # where the current language lives) -- avoids a second `fetch_project_facts` round trip
        # just to answer "what language is this" for `plan()`. Read after `gather_units()`, never
        # before.
        self.current_language = ""

    def resolve_run(self, thread_id: str) -> PipelineRun:
        run = get_run(thread_id, self.database_config)
        if run is None:
            raise ValueError(f"No ingestion run found for thread_id={thread_id!r}")
        return run

    def resolve_repo_id(self, thread_id: str) -> str:
        return self.resolve_run(thread_id).repo_id

    def gather_units(self, thread_id: str, repo_id: str, repo_path: str | None = None) -> list[MigrationUnit]:
        facts = fetch_project_facts(self.query_runner, thread_id, repo_id)
        self.current_language = ", ".join(facts.repository.primary_languages)
        units = build_migration_units(facts, repo_path)

        infra_paths = fetch_files_by_classification(self.query_runner, repo_id, ["infra", "build"])
        infra_unit = build_infra_unit(infra_paths)
        if infra_unit:
            units.append(infra_unit)
        return units

    def gather_dependencies(self, repo_id: str, repo_path: str) -> list[Dependency]:
        manifest_paths = fetch_files_by_classification(self.query_runner, repo_id, ["build"])
        return scan_dependencies(repo_path, manifest_paths)

    def plan(self, migration_request: str, units: list[MigrationUnit], current_language: str = "") -> MigrationPlan:
        return self.planning_agent.run(migration_request, units, current_language)

    def propose_dependency_mappings(
        self, migration_request: str, dependencies: list[Dependency], plan: MigrationPlan
    ) -> list[DependencyMapping]:
        if not self.dependency_mapping_agent or not dependencies:
            return []
        return self.dependency_mapping_agent.run(migration_request, dependencies, plan.target_language, plan.same_language)

    def verify_dependency_mappings(self, mappings: list[DependencyMapping]) -> list[DependencyMapping]:
        if not self.registry_client or not mappings:
            return mappings
        return run_registry_verification(mappings, self.registry_client)

    def generate(
        self,
        migration_request: str,
        units: list[MigrationUnit],
        plan: MigrationPlan,
        guidelines: list[RetrievedGuideline],
        repo_path: str | None = None,
        dependency_mappings: list[DependencyMapping] | None = None,
    ) -> list[GeneratedUnit]:
        task_by_unit = {task.unit_id: task for task in plan.tasks}
        code_units = [u for u in units if u.unit_type != "infra"]
        infra_units = [u for u in units if u.unit_type == "infra"]

        generated: list[GeneratedUnit] = []
        for unit in code_units:
            task = task_by_unit.get(unit.unit_id)
            task_description = task.description if task else f"Migrate this {unit.unit_type} per the migration request."
            generated.append(self.generation_agent.run(migration_request, unit, task_description, guidelines))

        # Infra generation runs last and deliberately sees the real current file content (unlike
        # every other unit) -- see `infra_generator.py`'s docstring -- plus a summary of what the
        # other units just produced, since a Dockerfile/docker-compose.yml needs to know what
        # services actually came out of the migration.
        if infra_units and self.infra_generation_agent and repo_path:
            current_files = _read_files(repo_path, infra_units[0].file_paths)
            generated_unit_file_paths = {g.name: [f.file_path for f in g.files] for g in generated}
            generated.append(
                self.infra_generation_agent.run(
                    migration_request, plan.summary, current_files, generated_unit_file_paths,
                    dependency_mappings, guidelines,
                )
            )
        return generated

    def validate(
        self, generated_units: list[GeneratedUnit], units: list[MigrationUnit] | None = None
    ) -> list[FileValidation]:
        # `ValidationAgent` only reads `file_path`/`modified_content`, so a generated file (which
        # has no "original") fits its `FileModification` shape without needing a parallel check.
        modifications = [
            FileModification(file_path=f.file_path, original_content="", modified_content=f.content, task_description="")
            for unit in generated_units
            for f in unit.files
        ]
        validations = self.validation_agent.run(modifications)
        if units:
            validations = flag_missing_response_fields(units, generated_units, validations)
        return validations

    def run(self, thread_id: str, migration_request: str) -> MigrationResult:
        run_row = self.resolve_run(thread_id)
        units = self.gather_units(thread_id, run_row.repo_id, run_row.repo_path)
        dependencies = self.gather_dependencies(run_row.repo_id, run_row.repo_path)
        guidelines = self.guideline_agent.query(migration_request) if self.guideline_agent else []
        plan = self.plan(migration_request, units, self.current_language)
        dependency_mappings = self.propose_dependency_mappings(migration_request, dependencies, plan)
        dependency_mappings = self.verify_dependency_mappings(dependency_mappings)
        generated_units = self.generate(migration_request, units, plan, guidelines, run_row.repo_path, dependency_mappings)
        validations = self.validate(generated_units, units)
        return MigrationResult(
            thread_id=thread_id,
            repo_id=run_row.repo_id,
            units=units,
            plan=plan,
            guidelines=guidelines,
            generated_units=generated_units,
            dependencies=dependencies,
            dependency_mappings=dependency_mappings,
            validations=validations,
        )

    def save(self, result: MigrationResult, migration_request: str) -> Path:
        output_dir = write_migration(
            self.output_root,
            result.thread_id,
            migration_request,
            result.units,
            result.plan,
            result.generated_units,
            result.validations,
            result.dependency_mappings,
        )
        result.output_dir = output_dir
        return output_dir


def _read_files(repo_path: str, file_paths: list[str]) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in file_paths:
        try:
            files[path] = (Path(repo_path) / path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return files

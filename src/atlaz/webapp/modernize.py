"""Modernize page -- two modes, both grounded in the project's knowledge
graph and both propose-only (never write back into the ingested repo):

- Targeted change: "change this feature" -- `atlaz.enhancement`. Finds a
  keyword-matched subset of impacted files, drafts a plan, and patches each
  file's *own current content* in place.
- Full migration: "migrate this to an entirely new stack" -- `atlaz.
  migration`. Pulls the *whole* knowledge graph (the same fact assembly
  HLD/LLD generation uses), groups it into units (one per business
  capability, or per service/whole-project as fallbacks), and generates
  fresh code per unit grounded only in that graph understanding -- the
  original file source is never shown to the LLM.

Both run synchronously, in-process. Review the diffs/generated files and
download the proposal (or find it under `outputs/<thread_id>/
{modifications,migrations}/<timestamp>/`) to apply manually.
"""

from __future__ import annotations

import difflib
import io
import zipfile
from pathlib import Path

import streamlit as st

from atlaz.audit.models import PipelineRun
from atlaz.audit.repository import list_completed_runs
from atlaz.enhancement.guideline_store import GuidelineRetrievalAgent, MilvusLiteVectorIndex, default_embed_fn
from atlaz.enhancement.impact_analysis import ImpactAnalysisAgent
from atlaz.enhancement.modifier import CodeModificationAgent
from atlaz.enhancement.output_writer import write_modifications
from atlaz.enhancement.planner import PlanningAgent
from atlaz.enhancement.service import EnhancementResult, EnhancementService
from atlaz.enhancement.validator import ValidationAgent
from atlaz.llm.client import build_llm_client
from atlaz.migration.dependency_mapper import DependencyMappingAgent
from atlaz.migration.dependency_verifier import HttpRegistryClient
from atlaz.migration.generator import UnitMigrationAgent
from atlaz.migration.infra_generator import InfraMigrationAgent
from atlaz.migration.models import DependencyMapping
from atlaz.migration.output_writer import write_migration
from atlaz.migration.planner import MigrationPlanningAgent
from atlaz.migration.service import MigrationResult, MigrationService
from atlaz.reasoning.neo4j_query_runner import Neo4jReasoningStore
from atlaz.shared.config import PipelineConfig
from atlaz.webapp import style
from atlaz.webapp.project_picker import select_project

_LANGUAGE_BY_SUFFIX = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".java": "java", ".cs": "csharp", ".go": "go", ".rb": "ruby", ".php": "php", ".rs": "rust",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".sql": "sql", ".sh": "bash", ".html": "html", ".css": "css",
}

_TARGETED_MODE = "🎯 Targeted change"
_MIGRATION_MODE = "🌐 Full migration"


def _heading() -> None:
    style.page_heading(
        "🛠️ Modernize",
        "STEP 3",
        "Describe a change in plain English. AtlaZ grounds everything in the knowledge graph and "
        "never writes back to your repository -- review and download the proposal.",
    )


def render() -> None:
    """Standalone entry point -- picks its own project. `main.py`'s
    single-page layout calls `render_body()` instead, with a project already
    chosen by the shared picker above this section."""
    try:
        runs = list_completed_runs()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        _heading()
        st.error(f"Couldn't reach the audit database: {exc}")
        return

    if not runs:
        _heading()
        st.info("No ingested projects yet. Use **Ingest** above to get started.")
        return

    render_body(select_project(runs))


def render_body(run: PipelineRun) -> None:
    _heading()
    mode = st.radio(
        "What kind of change?",
        [_TARGETED_MODE, _MIGRATION_MODE],
        horizontal=True,
        key="modernize_mode",
        captions=[
            "Patch a keyword-matched subset of existing files in place.",
            "Regenerate the whole project from the knowledge graph -- no original code shown to the LLM.",
        ],
    )

    if mode == _TARGETED_MODE:
        _render_targeted_change(run)
    else:
        _render_full_migration(run)


# ---------------------------------------------------------------------------
# Targeted change (atlaz.enhancement)
# ---------------------------------------------------------------------------


def _render_targeted_change(run: PipelineRun) -> None:
    request = st.text_area(
        "What do you want to change?",
        placeholder="e.g. Replace the deprecated requests calls in the billing service with httpx, "
        "and add retry/backoff.",
        key="modernize_request",
    )

    if st.button("Analyze & modernize", type="primary", disabled=not request.strip()):
        _run_targeted_change(run, request)

    state = st.session_state.get(f"modernize::{run.thread_id}")
    if state:
        st.divider()
        _render_targeted_result(run, state["result"], state["request"])


def _run_targeted_change(run: PipelineRun, request: str) -> None:
    config = PipelineConfig.from_env()
    guideline_agent = _build_guideline_agent(config)

    try:
        with st.spinner("Reading the knowledge graph, drafting a plan, and generating code..."):
            llm_client = build_llm_client(config.llm)
            with Neo4jReasoningStore(config.neo4j) as store:
                service = EnhancementService(
                    ImpactAnalysisAgent(store.run),
                    CodeModificationAgent(llm_client),
                    guideline_agent,
                    PlanningAgent(llm_client),
                    ValidationAgent(),
                )
                result = service.run(run.thread_id, request)
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        st.error(f"Couldn't draft a modernization proposal: {exc}")
        return

    st.session_state[f"modernize::{run.thread_id}"] = {"result": result, "request": request}
    st.session_state.pop(f"modernize_saved::{run.thread_id}", None)


def _render_targeted_result(run: PipelineRun, result: EnhancementResult, request: str) -> None:
    c1, c2, c3 = st.columns(3)
    style.stat_card(c1, len(result.impact.files), "Impacted files", "good")
    style.stat_card(c2, len(result.modifications), "Files drafted", "good")
    flagged = sum(1 for v in result.validations if not v.syntax_valid or v.security_issues)
    style.stat_card(c3, flagged, "Flagged on review", "risk" if flagged else "good")
    st.write("")

    if result.skipped_files:
        st.warning("Impacted per the graph, but not found on disk (skipped): " + ", ".join(result.skipped_files))

    plan_tab, files_tab, guidelines_tab = st.tabs(["🧭 Plan", "📝 Proposed changes", "📚 Guidelines used"])

    with plan_tab:
        if result.plan:
            st.markdown(result.plan.summary)
        else:
            st.caption("No planning step ran for this request.")
        if result.impact.files:
            st.markdown("**Impacted files (via the knowledge graph):**")
            for f in result.impact.files:
                st.markdown(f"- `{f.file_path}` — {f.reason}")

    with files_tab:
        if not result.modifications:
            st.caption("No modifications were generated for this request.")
        validation_by_file = {v.file_path: v for v in result.validations}
        for mod in result.modifications:
            validation = validation_by_file.get(mod.file_path)
            flagged_file = bool(validation and (not validation.syntax_valid or validation.security_issues))
            icon = "⚠️" if flagged_file else "✅"
            with st.expander(f"{icon} `{mod.file_path}`", expanded=flagged_file):
                _render_validation(validation)
                lang = _guess_language(mod.file_path)
                original_col, modified_col = st.columns(2)
                original_col.caption("Original")
                original_col.code(mod.original_content, language=lang)
                modified_col.caption("Modified (proposed)")
                modified_col.code(mod.modified_content, language=lang)
                st.caption("Unified diff")
                st.code(_unified_diff(mod.file_path, mod.original_content, mod.modified_content), language="diff")

    with guidelines_tab:
        _render_guidelines(result.guidelines)

    st.divider()
    if st.button("💾 Save proposal to outputs/", key=f"save_{run.thread_id}"):
        output_dir = write_modifications(
            "outputs", run.thread_id, request, result.impact, result.guidelines,
            result.modifications, result.plan, result.validations,
        )
        result.output_dir = output_dir
        st.session_state[f"modernize_saved::{run.thread_id}"] = output_dir

    _render_save_download(run, f"modernize_saved::{run.thread_id}", f"{run.repo_id}-modernization.zip", "download_targeted")


# ---------------------------------------------------------------------------
# Full migration (atlaz.migration)
# ---------------------------------------------------------------------------


def _render_full_migration(run: PipelineRun) -> None:
    request = st.text_area(
        "What are you migrating to?",
        placeholder="e.g. Migrate this Flask monolith to a FastAPI microservices architecture, "
        "one service per business capability.",
        key="migrate_request",
    )
    st.caption(
        "Full migration regenerates the project from the knowledge graph's understanding of it -- "
        "the original file source is never shown to the LLM (except the infra/build unit -- "
        "Dockerfile, CI config, dependency manifests -- which is declarative config, not business "
        "logic, so its real current content is shown on purpose). Best for a genuine stack/"
        "architecture change; use **Targeted change** for a scoped edit to existing files."
    )

    if st.button("Analyze & plan migration", type="primary", disabled=not request.strip()):
        _run_full_migration_analysis(run, request)

    pending = st.session_state.get(f"migrate_pending::{run.thread_id}")
    if pending:
        st.divider()
        _render_pending_dependency_confirmation(run, pending)
        return

    state = st.session_state.get(f"migrate::{run.thread_id}")
    if state:
        st.divider()
        _render_migration_result(run, state["result"], state["request"])


def _run_full_migration_analysis(run: PipelineRun, request: str) -> None:
    """Stage 1: resolve the run, gather units/dependencies, plan (including
    the same-language vs. cross-language call), and propose + registry-
    verify a dependency mapping. A same-language request (or one with no
    dependencies to map) proceeds straight to generation; a cross-language
    request with dependencies pauses here for human confirmation -- see
    `_render_pending_dependency_confirmation`.
    """
    config = PipelineConfig.from_env()
    guideline_agent = _build_guideline_agent(config)

    try:
        with st.spinner("Reading the whole knowledge graph and drafting a migration plan..."):
            llm_client = build_llm_client(config.llm)
            with Neo4jReasoningStore(config.neo4j) as store:
                service = MigrationService(
                    store.run,
                    MigrationPlanningAgent(llm_client),
                    UnitMigrationAgent(llm_client),
                    guideline_agent,
                    ValidationAgent(),
                    InfraMigrationAgent(llm_client),
                    DependencyMappingAgent(llm_client),
                    HttpRegistryClient(),
                )
                run_row = service.resolve_run(run.thread_id)
                units = service.gather_units(run.thread_id, run_row.repo_id, run_row.repo_path)
                dependencies = service.gather_dependencies(run_row.repo_id, run_row.repo_path)
                guidelines = guideline_agent.query(request) if guideline_agent else []
                plan = service.plan(request, units, service.current_language)
                dependency_mappings = service.propose_dependency_mappings(request, dependencies, plan)
                dependency_mappings = service.verify_dependency_mappings(dependency_mappings)
    except ValueError as exc:
        st.error(str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        st.error(f"Couldn't draft a migration plan: {exc}")
        return

    staged = {
        "request": request, "repo_path": run_row.repo_path, "repo_id": run_row.repo_id,
        "units": units, "plan": plan, "guidelines": guidelines,
        "dependencies": dependencies, "dependency_mappings": dependency_mappings,
    }
    st.session_state.pop(f"migrate::{run.thread_id}", None)
    st.session_state.pop(f"migrate_saved::{run.thread_id}", None)

    if not plan.same_language and dependencies:
        st.session_state[f"migrate_pending::{run.thread_id}"] = staged
    else:
        st.session_state.pop(f"migrate_pending::{run.thread_id}", None)
        _finish_full_migration(run, staged)


def _render_pending_dependency_confirmation(run: PipelineRun, staged: dict) -> None:
    plan = staged["plan"]
    st.warning(
        f"Cross-language migration to **{plan.target_language or 'the target stack'}** detected. Review "
        "(and edit if needed) the proposed dependency replacements below before generating code -- "
        "existence in the target registry is verified where possible, but whether a replacement truly "
        "covers this codebase's actual usage of the original package always needs a human check."
    )

    rows = [
        {
            "Current": f"{m.current_name} {m.current_version}",
            "Ecosystem": m.current_ecosystem,
            "Proposed replacement": m.target_name,
            "Target version": m.target_version,
            "Target ecosystem": m.target_ecosystem,
            "Verified": m.verified,
            "Note": m.verification_note,
        }
        for m in staged["dependency_mappings"]
    ]
    edited_rows = st.data_editor(
        rows,
        key=f"dep_editor_{run.thread_id}",
        num_rows="fixed",
        disabled=["Current", "Ecosystem", "Verified", "Note"],
        width="stretch",
    )

    if st.button("✅ Confirm dependencies & generate", type="primary", key=f"confirm_deps_{run.thread_id}"):
        confirmed = [
            DependencyMapping(
                current_name=m.current_name, current_version=m.current_version, current_ecosystem=m.current_ecosystem,
                target_name=row["Proposed replacement"], target_version=row["Target version"],
                target_ecosystem=row["Target ecosystem"], justification=m.justification,
                same_language=m.same_language, verified=m.verified, verification_note=m.verification_note,
            )
            for m, row in zip(staged["dependency_mappings"], edited_rows, strict=True)
        ]
        st.session_state.pop(f"migrate_pending::{run.thread_id}", None)
        _finish_full_migration(run, {**staged, "dependency_mappings": confirmed})
        st.rerun()


def _finish_full_migration(run: PipelineRun, staged: dict) -> None:
    """Stage 2: generate + validate using the (possibly human-confirmed)
    dependency mapping. No Neo4j access needed here -- generation is LLM +
    disk (for the infra unit) only, which is what lets this run as a
    separate step/rerun from stage 1 without keeping a database connection
    open across them.
    """
    config = PipelineConfig.from_env()

    try:
        with st.spinner("Generating code..."):
            llm_client = build_llm_client(config.llm)
            service = MigrationService(
                lambda cypher, params: [],
                planning_agent=None,
                generation_agent=UnitMigrationAgent(llm_client),
                validation_agent=ValidationAgent(),
                infra_generation_agent=InfraMigrationAgent(llm_client),
            )
            generated_units = service.generate(
                staged["request"], staged["units"], staged["plan"], staged["guidelines"],
                staged["repo_path"], staged["dependency_mappings"],
            )
            validations = service.validate(generated_units, staged["units"])
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        st.error(f"Couldn't generate the migration: {exc}")
        return

    result = MigrationResult(
        thread_id=run.thread_id, repo_id=staged["repo_id"], units=staged["units"], plan=staged["plan"],
        guidelines=staged["guidelines"], generated_units=generated_units, dependencies=staged["dependencies"],
        dependency_mappings=staged["dependency_mappings"], validations=validations,
    )
    st.session_state[f"migrate::{run.thread_id}"] = {"result": result, "request": staged["request"]}
    st.session_state.pop(f"migrate_saved::{run.thread_id}", None)


def _render_migration_result(run: PipelineRun, result: MigrationResult, request: str) -> None:
    generated_files = sum(len(u.files) for u in result.generated_units)
    c1, c2, c3 = st.columns(3)
    style.stat_card(c1, len(result.units), "Migration units", "good")
    style.stat_card(c2, generated_files, "Files generated", "good")
    flagged = sum(1 for v in result.validations if not v.syntax_valid or v.security_issues)
    style.stat_card(c3, flagged, "Flagged on review", "risk" if flagged else "good")
    st.write("")

    plan_tab, units_tab, deps_tab, guidelines_tab = st.tabs(
        ["🧭 Plan", "📦 Generated units", "🧩 Dependencies", "📚 Guidelines used"]
    )

    with plan_tab:
        st.markdown(result.plan.summary)
        if result.plan.tasks:
            st.markdown("**Units migrated:**")
            for task in result.plan.tasks:
                st.markdown(f"- `{task.unit_id}` — **{task.title}**: {task.description}")

    with units_tab:
        if not result.generated_units:
            st.caption("No units were generated for this request.")
        validation_by_file = {v.file_path: v for v in result.validations}
        units_by_id = {u.unit_id: u for u in result.units}
        for gen_unit in result.generated_units:
            unit_flagged = any(
                validation_by_file.get(f.file_path) and (
                    not validation_by_file[f.file_path].syntax_valid or validation_by_file[f.file_path].security_issues
                )
                for f in gen_unit.files
            )
            icon = "⚠️" if unit_flagged else "✅"
            with st.expander(f"{icon} {gen_unit.name} ({gen_unit.unit_type}) -- {len(gen_unit.files)} file(s)"):
                source_unit = units_by_id.get(gen_unit.unit_id)
                if source_unit and gen_unit.unit_type == "infra":
                    with st.expander("Current file content shown to the LLM (infra is the one exception)", expanded=False):
                        st.text(source_unit.description or "(empty)")
                elif source_unit:
                    with st.expander("Knowledge-graph understanding used (no original source code)", expanded=False):
                        st.text(source_unit.description or "(empty)")
                if not gen_unit.files:
                    st.caption("No files were generated for this unit.")
                for f in gen_unit.files:
                    validation = validation_by_file.get(f.file_path)
                    st.markdown(f"**`{f.file_path}`**")
                    _render_validation(validation)
                    st.code(f.content, language=_guess_language(f.file_path))

    with deps_tab:
        if not result.dependencies:
            st.caption("No dependency manifests were found for this project.")
        elif not result.dependency_mappings:
            st.caption(f"{len(result.dependencies)} dependencies found; no mapping was proposed (dependency mapping not configured).")
        else:
            st.caption(
                f"Target: {result.plan.target_language or 'unknown'} "
                f"({'same language' if result.plan.same_language else 'cross-language'})"
            )
            for m in result.dependency_mappings:
                status = "✅ verified" if m.verified else "⚠️ unverified"
                st.markdown(
                    f"- `{m.current_name} {m.current_version}` ({m.current_ecosystem}) → "
                    f"`{m.target_name} {m.target_version}` ({m.target_ecosystem}) -- {status}"
                )
                if m.justification:
                    st.caption(m.justification)
                if m.verification_note:
                    st.caption(m.verification_note)

    with guidelines_tab:
        _render_guidelines(result.guidelines)

    st.divider()
    if st.button("💾 Save proposal to outputs/", key=f"save_migrate_{run.thread_id}"):
        output_dir = write_migration(
            "outputs", run.thread_id, request, result.units, result.plan,
            result.generated_units, result.validations, result.dependency_mappings,
        )
        result.output_dir = output_dir
        st.session_state[f"migrate_saved::{run.thread_id}"] = output_dir

    _render_save_download(run, f"migrate_saved::{run.thread_id}", f"{run.repo_id}-migration.zip", "download_migration")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_guideline_agent(config: PipelineConfig) -> GuidelineRetrievalAgent | None:
    if not config.guideline_store.enabled:
        return None
    try:
        index = MilvusLiteVectorIndex(config.guideline_store.db_path, config.guideline_store.collection_name)
        agent = GuidelineRetrievalAgent(index, default_embed_fn(config.llm))
        agent.populate_default_guidelines()
        return agent
    except RuntimeError:
        return None  # e.g. pymilvus not installed -- flow still works without guidelines


def _render_validation(validation) -> None:
    if not validation:
        return
    for warning in validation.warnings:
        st.warning(warning)
    for issue in validation.security_issues:
        st.error(issue)


def _render_guidelines(guidelines) -> None:
    if guidelines:
        for g in guidelines:
            st.markdown(f"- **[{g.category}] {g.title}** (score {g.score:.3f}): {g.content}")
    else:
        st.caption("No guidelines were retrieved for this request.")


def _render_save_download(run: PipelineRun, session_key: str, zip_name: str, widget_key: str) -> None:
    saved_dir: Path | None = st.session_state.get(session_key)
    if not saved_dir:
        return
    st.success(f"Saved to `{saved_dir}`")
    st.download_button(
        "⬇ Download proposal (.zip)",
        _zip_output_dir(saved_dir),
        file_name=zip_name,
        mime="application/zip",
        key=f"{widget_key}_{run.thread_id}",
    )


def _guess_language(file_path: str) -> str:
    idx = file_path.rfind(".")
    return _LANGUAGE_BY_SUFFIX.get(file_path[idx:].lower(), "") if idx != -1 else ""


def _unified_diff(file_path: str, original: str, modified: str) -> str:
    diff = difflib.unified_diff(
        original.splitlines(keepends=True),
        modified.splitlines(keepends=True),
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    text = "".join(diff).strip()
    return text or "(no textual difference)"


def _zip_output_dir(output_dir: Path) -> bytes:
    root = Path(output_dir)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in root.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(root.parent))
    return buf.getvalue()


if __name__ == "__main__":
    st.set_page_config(page_title="AtlaZ — Modernize", page_icon="🛠️", layout="wide")
    style.inject()
    render()

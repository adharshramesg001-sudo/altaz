"""Writes a migration proposal to `outputs/<thread_id>/migrations/<timestamp>/`
-- a separate top-level folder from `atlaz.enhancement.output_writer`'s
`modifications/` (patches existing files), since these are two different
flows that should never be confused for one another on disk. Never writes
into the ingested repository -- propose-only, like the enhancement flow.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from atlaz.enhancement.models import FileValidation
from atlaz.migration.models import DependencyMapping, GeneratedUnit, MigrationPlan, MigrationUnit


def write_migration(
    output_root: Path | str,
    thread_id: str,
    migration_request: str,
    units: list[MigrationUnit],
    plan: MigrationPlan,
    generated_units: list[GeneratedUnit],
    validations: list[FileValidation] | None = None,
    dependency_mappings: list[DependencyMapping] | None = None,
) -> Path:
    validations = validations or []
    dependency_mappings = dependency_mappings or []
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(output_root) / thread_id / "migrations" / timestamp
    files_dir = run_dir / "files"

    for unit in generated_units:
        for generated_file in unit.files:
            target = files_dir / generated_file.file_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated_file.content, encoding="utf-8")

    manifest = {
        "thread_id": thread_id,
        "migration_request": migration_request,
        "generated_at": timestamp,
        "units": [asdict(u) for u in units],
        "plan_summary": plan.summary,
        "plan_tasks": [asdict(t) for t in plan.tasks],
        "target_language": plan.target_language,
        "same_language": plan.same_language,
        "generated_files": [f.file_path for u in generated_units for f in u.files],
        "dependency_mappings": [asdict(m) for m in dependency_mappings],
        "validations": [asdict(v) for v in validations],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(
        _render_report(thread_id, migration_request, plan, generated_units, validations, dependency_mappings),
        encoding="utf-8",
    )
    return run_dir


def _render_report(
    thread_id: str,
    migration_request: str,
    plan: MigrationPlan,
    generated_units: list[GeneratedUnit],
    validations: list[FileValidation],
    dependency_mappings: list[DependencyMapping],
) -> str:
    lines = [
        "# AtlaZ Migration Report",
        "",
        f"**Run:** `{thread_id}`",
        f"**Request:** {migration_request}",
        f"**Target language:** {plan.target_language or 'unknown'} "
        + f"({'same language' if plan.same_language else 'cross-language migration'})",
        "",
        "## Migration plan",
        "",
        plan.summary,
    ]
    if plan.tasks:
        lines += ["", "**Units migrated:**", ""]
        for task in plan.tasks:
            lines.append(f"- `{task.unit_id}` — **{task.title}**: {task.description}")

    if dependency_mappings:
        lines += ["", "## Dependency mapping", ""]
        for m in dependency_mappings:
            status = "✅ verified" if m.verified else "⚠️ unverified"
            lines.append(
                f"- `{m.current_name} {m.current_version}` ({m.current_ecosystem}) -> "
                f"`{m.target_name} {m.target_version}` ({m.target_ecosystem}) -- {status}. {m.justification}"
                + (f" _{m.verification_note}_" if m.verification_note else "")
            )

    validation_by_file = {v.file_path: v for v in validations}
    lines += ["", "## Generated units", ""]
    if not generated_units:
        lines.append("_No units were generated._")
    for unit in generated_units:
        lines.append(f"### {unit.name} ({unit.unit_type})")
        lines.append("")
        if not unit.files:
            lines.append("_No files were generated for this unit._")
        for generated_file in unit.files:
            validation = validation_by_file.get(generated_file.file_path)
            status = "✅ passed checks"
            if validation and (not validation.syntax_valid or validation.security_issues):
                status = "⚠️ flagged on review"
            lines.append(f"#### `{generated_file.file_path}` — {status}")
            lines.append("")
            if validation:
                for warning in validation.warnings:
                    lines.append(f"- ⚠️ {warning}")
                for issue in validation.security_issues:
                    lines.append(f"- 🔒 {issue}")
                if validation.warnings or validation.security_issues:
                    lines.append("")
            lines.append(f"```{_suffix(generated_file.file_path).lstrip('.')}")
            lines.append(generated_file.content)
            lines.append("```")
            lines.append("")

    return "\n".join(lines)


def _suffix(file_path: str) -> str:
    idx = file_path.rfind(".")
    return file_path[idx:] if idx != -1 else ""

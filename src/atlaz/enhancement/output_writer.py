"""Writes generated modifications to a top-level `outputs/` directory --
deliberately never back into the ingested repository's own working tree
(unlike an approve-and-overwrite step): this flow is propose-only, so the
original source is never touched and every run's output is independently
inspectable and diffable against it.

Layout: `outputs/<thread_id>/modifications/<timestamp>/files/<relative
path>` holds the full modified content of each file (mirroring the
original repo's relative paths), alongside `manifest.json` (machine-
readable summary) and `report.md` (human-readable summary with unified
diffs).
"""

from __future__ import annotations

import difflib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from atlaz.enhancement.models import (
    FileModification,
    FileValidation,
    ImpactAnalysisResult,
    ModificationPlan,
    RetrievedGuideline,
)


def write_modifications(
    output_root: Path | str,
    thread_id: str,
    enhancement_request: str,
    impact: ImpactAnalysisResult,
    guidelines: list[RetrievedGuideline],
    modifications: list[FileModification],
    plan: ModificationPlan | None = None,
    validations: list[FileValidation] | None = None,
) -> Path:
    validations = validations or []
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(output_root) / thread_id / "modifications" / timestamp
    files_dir = run_dir / "files"

    for mod in modifications:
        target = files_dir / mod.file_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(mod.modified_content, encoding="utf-8")

    manifest = {
        "thread_id": thread_id,
        "enhancement_request": enhancement_request,
        "generated_at": timestamp,
        "matched_nodes": impact.matched_nodes,
        "impacted_files": [asdict(f) for f in impact.files],
        "guidelines_used": [asdict(g) for g in guidelines],
        "modified_files": [mod.file_path for mod in modifications],
        "plan_summary": plan.summary if plan else None,
        "plan_tasks": [asdict(t) for t in plan.tasks] if plan else [],
        "validations": [asdict(v) for v in validations],
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(
        _render_report(thread_id, enhancement_request, impact, guidelines, modifications, plan, validations),
        encoding="utf-8",
    )
    return run_dir


def _render_report(
    thread_id: str,
    enhancement_request: str,
    impact: ImpactAnalysisResult,
    guidelines: list[RetrievedGuideline],
    modifications: list[FileModification],
    plan: ModificationPlan | None,
    validations: list[FileValidation],
) -> str:
    lines = [
        "# AtlaZ Enhancement Report",
        "",
        f"**Run:** `{thread_id}`",
        f"**Request:** {enhancement_request}",
        "",
        "## Retrieval — knowledge-graph impact analysis",
        "",
    ]
    if impact.files:
        for f in impact.files:
            lines.append(f"- `{f.file_path}` — {f.reason} ({', '.join(f.matched_node_labels) or 'n/a'})")
    else:
        lines.append("_No files in the knowledge graph matched this request._")

    if guidelines:
        lines += ["", "## Retrieved enterprise guidelines", ""]
        for g in guidelines:
            lines.append(f"- **[{g.category}] {g.title}** (score {g.score:.3f}): {g.content}")

    if plan:
        lines += ["", "## Modernization plan", "", plan.summary]
        if plan.tasks:
            lines += ["", "**Tasks:**", ""]
            for task in plan.tasks:
                lines.append(f"- `{task.file_path}` — **{task.title}**: {task.description}")

    validation_by_file = {v.file_path: v for v in validations}
    lines += ["", "## Modifications", ""]
    if not modifications:
        lines.append("_No modifications were generated._")
    for mod in modifications:
        validation = validation_by_file.get(mod.file_path)
        status = "✅ passed checks"
        if validation and (not validation.syntax_valid or validation.security_issues):
            status = "⚠️ flagged on review"
        lines.append(f"### `{mod.file_path}` — {status}")
        lines.append("")
        if validation:
            for warning in validation.warnings:
                lines.append(f"- ⚠️ {warning}")
            for issue in validation.security_issues:
                lines.append(f"- 🔒 {issue}")
            if validation.warnings or validation.security_issues:
                lines.append("")
        diff = difflib.unified_diff(
            mod.original_content.splitlines(keepends=True),
            mod.modified_content.splitlines(keepends=True),
            fromfile=f"a/{mod.file_path}",
            tofile=f"b/{mod.file_path}",
        )
        diff_text = "".join(diff).strip()
        lines.append("```diff")
        lines.append(diff_text if diff_text else "(no textual difference)")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)

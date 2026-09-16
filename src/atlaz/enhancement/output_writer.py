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

from atlaz.enhancement.models import FileModification, ImpactAnalysisResult, RetrievedGuideline


def write_modifications(
    output_root: Path | str,
    thread_id: str,
    enhancement_request: str,
    impact: ImpactAnalysisResult,
    guidelines: list[RetrievedGuideline],
    modifications: list[FileModification],
) -> Path:
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
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (run_dir / "report.md").write_text(
        _render_report(thread_id, enhancement_request, impact, guidelines, modifications), encoding="utf-8"
    )
    return run_dir


def _render_report(
    thread_id: str,
    enhancement_request: str,
    impact: ImpactAnalysisResult,
    guidelines: list[RetrievedGuideline],
    modifications: list[FileModification],
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

    lines += ["", "## Modifications", ""]
    if not modifications:
        lines.append("_No modifications were generated._")
    for mod in modifications:
        lines.append(f"### `{mod.file_path}`")
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

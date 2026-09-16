"""Writes generated HLD/LLD documents to a top-level `outputs/` directory,
namespaced by the caller-supplied `project_id` -- mirrors
`atlaz.enhancement.output_writer`'s layout convention (`outputs/<id>/...`),
keyed by `project_id` instead of `thread_id` here since one project may
regenerate its documentation across multiple ingestion runs and the
caller wants a stable folder to look in regardless of which run produced
the latest version.

Layout: `outputs/<project_id>/docs/<timestamp>/HLD.md`,
`.../LLD.md`, `.../manifest.json` (machine-readable summary of what was
pulled from the graph, for auditability).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from atlaz.docgen.models import ProjectFacts


def write_documents(
    output_root: Path | str,
    project_id: str,
    thread_id: str,
    hld_markdown: str,
    lld_markdown: str,
    facts: ProjectFacts,
) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(output_root) / project_id / "docs" / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    (run_dir / "HLD.md").write_text(hld_markdown, encoding="utf-8")
    (run_dir / "LLD.md").write_text(lld_markdown, encoding="utf-8")

    manifest = {
        "project_id": project_id,
        "thread_id": thread_id,
        "generated_at": timestamp,
        "repository": asdict(facts.repository),
        "counts": {
            "services": len(facts.services),
            "classes": len(facts.classes),
            "methods": len(facts.methods),
            "capabilities": len(facts.capabilities),
            "workflows": len(facts.workflows),
            "business_rules": len(facts.business_rules),
            "tables": len(facts.tables),
            "apis": len(facts.apis),
            "security_controls": len(facts.security_controls),
            "requirements": len(facts.requirements),
            "conflicts": len(facts.conflicts),
        },
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return run_dir

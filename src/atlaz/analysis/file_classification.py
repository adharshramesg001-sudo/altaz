"""File classification (LLD Section 5, node N1 `ingest_repo`).

Classifies every ingested file as exactly one of `source | config | build |
infra | docs | test`, reusing the signals `RepoIngestor` already computed
(`readme_paths`/`config_paths`/`manifest_paths`, per-file `language`) rather
than re-walking the filesystem. An unclassifiable file is tagged `unknown`,
excluded from AST parsing but retained for evidence-store completeness
(LLD Section 5, N1's documented failure mode).
"""

from __future__ import annotations

from atlaz.agents.domain_c.frd_extractor import is_test_file
from atlaz.ingestion.models import FileRecord, RepoInventory

INFRA_SUFFIXES = {".tf", ".tfvars", ".hcl"}
INFRA_FILENAMES = {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "jenkinsfile"}
INFRA_PATH_MARKERS = ("/.github/workflows/", "/infra/", "/deploy/", "/k8s/", "/kubernetes/", "/terraform/")
DOC_SUFFIXES = {".md", ".rst", ".adoc"}
DOC_PATH_MARKERS = ("/docs/", "/doc/")

FileClass = str  # "source" | "config" | "build" | "infra" | "docs" | "test" | "unknown"


def classify_file(file_record: FileRecord, inventory: RepoInventory) -> FileClass:
    path = file_record.path
    lower = f"/{path.lower()}"
    name_lower = path.rsplit("/", 1)[-1].lower()
    suffix = f".{name_lower.rsplit('.', 1)[-1]}" if "." in name_lower else ""

    if is_test_file(path):
        return "test"
    if name_lower in INFRA_FILENAMES or suffix in INFRA_SUFFIXES or lower.startswith(INFRA_PATH_MARKERS):
        return "infra"
    if path in inventory.readme_paths or suffix in DOC_SUFFIXES or lower.startswith(DOC_PATH_MARKERS):
        return "docs"
    if path in inventory.manifest_paths:
        return "build"
    if path in inventory.config_paths:
        return "config"
    if file_record.language:
        return "source"
    return "unknown"


def classify_inventory(inventory: RepoInventory) -> dict[str, FileClass]:
    return {f.path: classify_file(f, inventory) for f in inventory.files}

"""Looks up files by `File.classification` (already computed at ingestion
time by `analysis.file_classification` -- `source | config | build | infra |
docs | test | unknown`) for the current run's `repo_id`. Used to build the
migration flow's infra unit (`infra`/`build` files: Dockerfile,
docker-compose.yml, CI workflows, IaC, dependency manifests) and to find
manifest files for `dependency_scanner.py`.
"""

from __future__ import annotations

from atlaz.docgen.graph_facts import QueryRunner
from atlaz.reasoning.cypher_safety import ensure_read_only

_QUERY = """
MATCH (f:File {repo_id: $repo_id})
WHERE f.classification IN $classifications
RETURN f.path AS path
ORDER BY f.path
"""


def fetch_files_by_classification(query_runner: QueryRunner, repo_id: str, classifications: list[str]) -> list[str]:
    rows = query_runner(ensure_read_only(_QUERY), {"repo_id": repo_id, "classifications": classifications})
    return [row["path"] for row in rows if row.get("path")]

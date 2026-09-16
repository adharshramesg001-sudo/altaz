"""Orchestrates HLD/LLD generation end to end against an already-ingested
run: resolve the run (to confirm it exists and is queryable), read the
finished knowledge graph, render both documents, and (on request) write
them to `outputs/<project_id>/docs/`.

Deliberately not a LangGraph node -- like `atlaz.enhancement`, this is an
on-demand read against a finished run's graph, not part of the ingestion
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from atlaz.audit.repository import get_run
from atlaz.docgen.graph_facts import QueryRunner, fetch_project_facts
from atlaz.docgen.hld_generator import generate_hld
from atlaz.docgen.lld_generator import generate_lld
from atlaz.docgen.models import DocGenResult, ProjectFacts
from atlaz.docgen.output_writer import write_documents
from atlaz.llm.client import BaseLLMClient
from atlaz.shared.config import DatabaseConfig


@dataclass(slots=True)
class DocumentationService:
    llm_client: BaseLLMClient
    query_runner: QueryRunner
    output_root: Path | str = "outputs"
    database_config: DatabaseConfig | None = None

    def resolve_repo_id(self, thread_id: str) -> str:
        """Neo4j is one shared instance across every repo ever ingested
        (see `Neo4jWriter.write_batch`'s docstring) -- every graph query
        this service issues must be scoped to exactly this run's `repo_id`,
        resolved from the audit record `record_run_started` wrote it into,
        never left to match "whatever's in the graph"."""
        run = get_run(thread_id, self.database_config)
        if run is None:
            raise ValueError(f"No ingestion run found for thread_id={thread_id!r}")
        return run.repo_id

    def gather_facts(self, thread_id: str, repo_id: str) -> ProjectFacts:
        return fetch_project_facts(self.query_runner, thread_id, repo_id)

    def generate(self, thread_id: str) -> tuple[ProjectFacts, str, str]:
        repo_id = self.resolve_repo_id(thread_id)
        facts = self.gather_facts(thread_id, repo_id)
        hld = generate_hld(facts, self.llm_client)
        lld = generate_lld(facts)
        return facts, hld, lld

    def run(self, thread_id: str, project_id: str, *, save: bool = True) -> DocGenResult:
        facts, hld, lld = self.generate(thread_id)
        result = DocGenResult(project_id=project_id, thread_id=thread_id, hld_markdown=hld, lld_markdown=lld)
        if save:
            result.output_dir = write_documents(self.output_root, project_id, thread_id, hld, lld, facts)
        return result

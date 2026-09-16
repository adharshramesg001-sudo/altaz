"""Orchestrates cross-repo service correlation end to end against two
already-ingested runs: resolve both runs, read each finished knowledge
graph, scan each repo's source for outbound-call evidence, correlate in
both directions, and (on request) persist the result as `CALLS_SERVICE`
edges plus their evidence.

Deliberately not a LangGraph node -- like `atlaz.docgen`/`atlaz.enhancement`,
this is an on-demand operation against two finished runs, not part of the
ingestion pipeline (which only ever knows about one repo at a time).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from atlaz.audit.models import EvidenceRecord
from atlaz.audit.repository import get_run, record_evidence
from atlaz.crossrepo.matcher import correlate
from atlaz.crossrepo.models import ServiceLinkCandidate
from atlaz.crossrepo.scanner import scan_declared_service_names, scan_outbound_calls
from atlaz.docgen.graph_facts import QueryRunner, fetch_project_facts
from atlaz.shared.config import DatabaseConfig


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:64]


@dataclass(slots=True)
class CrossRepoLinkService:
    query_runner: QueryRunner
    database_config: DatabaseConfig | None = None

    def _resolve(self, thread_id: str) -> tuple[str, str]:
        run = get_run(thread_id, self.database_config)
        if run is None:
            raise ValueError(f"No ingestion run found for thread_id={thread_id!r}")
        return run.repo_id, run.repo_path

    def find_candidates(self, thread_id_a: str, thread_id_b: str) -> list[ServiceLinkCandidate]:
        repo_id_a, repo_path_a = self._resolve(thread_id_a)
        repo_id_b, repo_path_b = self._resolve(thread_id_b)

        facts_a = fetch_project_facts(self.query_runner, thread_id_a, repo_id_a)
        facts_b = fetch_project_facts(self.query_runner, thread_id_b, repo_id_b)

        signals_a = scan_outbound_calls(repo_path_a)
        signals_b = scan_outbound_calls(repo_path_b)
        names_a = scan_declared_service_names(repo_path_a)
        names_b = scan_declared_service_names(repo_path_b)

        candidates = correlate(facts_a, signals_a, facts_b, names_b)
        candidates += correlate(facts_b, signals_b, facts_a, names_a)
        return candidates

    def write(self, candidates: list[ServiceLinkCandidate]) -> int:
        """Persists each candidate as a `CALLS_SERVICE` edge, MATCHed on
        `(name, repo_id)` on both endpoints -- never through
        `Neo4jWriter.write_batch`'s generic edge writer, whose MATCH is
        natural-key-only with no `repo_id` qualifier (safe for a single
        repo's own writes, not safe for an edge meant to cross two repos)."""
        run_timestamp = time.time()
        written = 0
        for candidate in candidates:
            evidence_ids: list[str] = []
            records: list[EvidenceRecord] = []
            for ev in candidate.evidence:
                evidence_id = _content_hash(
                    ev.file or "", str(ev.line or ""), candidate.source_service, candidate.target_service
                )
                evidence_ids.append(evidence_id)
                records.append(
                    EvidenceRecord(
                        evidence_id=evidence_id,
                        source_type="source_code",
                        file_path=ev.file,
                        line_start=ev.line,
                        line_end=ev.line,
                        produced_by_node="crossrepo.service_correlation",
                        run_id=f"{candidate.source_repo_id}::{candidate.target_repo_id}",
                    )
                )
            record_evidence(records, self.database_config)

            self.query_runner(
                "MATCH (a:Service {name: $a_name, repo_id: $a_repo}) "
                "MATCH (b:Service {name: $b_name, repo_id: $b_repo}) "
                "MERGE (a)-[r:CALLS_SERVICE]->(b) "
                "SET r += $properties",
                {
                    "a_name": candidate.source_service,
                    "a_repo": candidate.source_repo_id,
                    "b_name": candidate.target_service,
                    "b_repo": candidate.target_repo_id,
                    "properties": {
                        "confidence": candidate.confidence,
                        "evidence_ids": evidence_ids,
                        "derivation_method": "cross_repo_service_correlation",
                        "status": "unconfirmed",
                        "scoring_weight_profile": "cross_repo",
                        "source_domain": "cross_repo",
                        "matched_on": candidate.matched_on,
                        "last_verified": run_timestamp,
                    },
                },
            )
            written += 1
        return written

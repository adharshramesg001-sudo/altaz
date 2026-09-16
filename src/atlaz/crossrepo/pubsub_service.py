"""Orchestrates async messaging correlation for one already-ingested run:
scan its source for message-queue/event-stream publish and consume call
sites, attribute each to a `Service`, and (on request) persist them as
`PUBLISHES`/`CONSUMES` edges onto a shared `Event` node.

Unlike `atlaz.crossrepo.service.CrossRepoLinkService`, this operates on a
*single* thread_id -- a queue/topic name is a precise, shared identifier
both sides already agree on by convention, so cross-repo linkage comes for
free from two repos' findings landing on the same `Event` node (keyed by
normalized topic, not by `repo_id`), not from an explicit two-repo
correlation pass.

Deliberately not a LangGraph node, for the same reason as the rest of
`atlaz.crossrepo`: this reads a finished run's graph and repo_path, not
part of the per-repo ingestion pipeline.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from atlaz.audit.models import EvidenceRecord
from atlaz.audit.repository import get_run, record_evidence
from atlaz.crossrepo.attribution import normalize_name, owning_service
from atlaz.crossrepo.models import PubSubFinding
from atlaz.crossrepo.scanner import scan_pubsub_signals
from atlaz.docgen.graph_facts import QueryRunner, fetch_project_facts
from atlaz.shared.config import DatabaseConfig

_EXTRACTION_CONFIDENCE = 0.7  # flat: no differential signal to grade on, unlike the sync matcher's route-overlap boost

_SUBSCRIPTION_SUFFIXES = ("-sub", "_sub", "-subscription", "_subscription", "-consumer", "_consumer")


def _normalize_topic(topic: str, direction: str, library: str) -> str:
    value = topic
    if library == "google_pubsub" and direction == "consume":
        for suffix in _SUBSCRIPTION_SUFFIXES:
            if value.endswith(suffix):
                value = value[: -len(suffix)]
                break
    return normalize_name(value)


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:64]


@dataclass(slots=True)
class PubSubLinkService:
    query_runner: QueryRunner
    database_config: DatabaseConfig | None = None

    def scan(self, thread_id: str) -> list[PubSubFinding]:
        run = get_run(thread_id, self.database_config)
        if run is None:
            raise ValueError(f"No ingestion run found for thread_id={thread_id!r}")

        facts = fetch_project_facts(self.query_runner, thread_id, run.repo_id)
        findings: list[PubSubFinding] = []
        for signal in scan_pubsub_signals(run.repo_path):
            service = owning_service(signal.evidence.file, facts.service_files)
            if service is None:
                continue  # evidence file isn't attributable to any known component
            findings.append(
                PubSubFinding(
                    repo_id=run.repo_id,
                    service=service,
                    direction=signal.direction,
                    topic=_normalize_topic(signal.topic, signal.direction, signal.library),
                    library=signal.library,
                    confidence=_EXTRACTION_CONFIDENCE,
                    evidence=signal.evidence,
                )
            )
        return findings

    def write(self, findings: list[PubSubFinding]) -> int:
        """Persists each finding as a `PUBLISHES`/`CONSUMES` edge from the
        finding's `Service` (MATCHed on `(name, repo_id)`, same
        collision-safety reasoning as `CrossRepoLinkService.write`) to a
        shared `Event` node -- deliberately keyed on `event_id` alone, no
        `repo_id`, since two repos referencing the same topic are meant to
        land on the same node. Not routed through `Neo4jWriter.write_batch`
        for the same reason as `CALLS_SERVICE`: that writer's generic node
        stamping would tag `Event` with whichever repo wrote it last, which
        is actively misleading for a node whose identity is meant to be
        shared."""
        run_timestamp = time.time()
        written = 0
        for finding in findings:
            evidence_id = _content_hash(
                finding.evidence.file or "", str(finding.evidence.line or ""), finding.service, finding.topic
            )
            record_evidence(
                [
                    EvidenceRecord(
                        evidence_id=evidence_id,
                        source_type="source_code",
                        file_path=finding.evidence.file,
                        line_start=finding.evidence.line,
                        line_end=finding.evidence.line,
                        produced_by_node="crossrepo.pubsub_scan",
                        run_id=finding.repo_id,
                    )
                ],
                self.database_config,
            )

            edge_type = "PUBLISHES" if finding.direction == "publish" else "CONSUMES"
            self.query_runner(
                f"MATCH (s:Service {{name: $service, repo_id: $repo_id}}) "
                "MERGE (e:Event {event_id: $event_id}) SET e += $event_properties "
                f"MERGE (s)-[r:{edge_type}]->(e) SET r += $edge_properties",
                {
                    "service": finding.service,
                    "repo_id": finding.repo_id,
                    "event_id": finding.topic,
                    "event_properties": {"name": finding.topic, "last_verified": run_timestamp},
                    "edge_properties": {
                        "confidence": finding.confidence,
                        "evidence_ids": [evidence_id],
                        "derivation_method": "pubsub_call_scan",
                        "status": "unconfirmed",
                        "source_domain": "cross_repo",
                        "library": finding.library,
                        "last_verified": run_timestamp,
                    },
                },
            )
            written += 1
        return written

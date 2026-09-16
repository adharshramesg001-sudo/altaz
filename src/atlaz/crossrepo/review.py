"""Read/update helpers for the `status="unconfirmed"` edges
`atlaz.crossrepo.service`/`atlaz.crossrepo.pubsub_service` write --
`CALLS_SERVICE` (sync) and `PUBLISHES`/`CONSUMES` (async). No HITL review
step existed for these when they shipped (documented as a follow-up in
both); this is that follow-up: list the unconfirmed edges touching one
repo, and let a reviewer confirm or reject each one.

Kept separate from the two writer services since this isn't about *finding*
new links, just reviewing ones already in the graph -- used by the
Streamlit app's Review tab (`atlaz.webapp.retrieve`).
"""

from __future__ import annotations

from dataclasses import dataclass

from atlaz.docgen.graph_facts import QueryRunner

_STATUSES = ("confirmed", "rejected")


@dataclass(slots=True)
class UnconfirmedLink:
    rel_id: int  # Neo4j internal relationship id -- stable handle for the SET below, not a domain key
    kind: str  # "calls_service" | "publishes" | "consumes"
    source: str
    source_repo_id: str
    target: str  # target Service name (calls_service) or Event topic (publishes/consumes)
    target_repo_id: str | None  # None for publishes/consumes -- Event carries no repo_id by design
    confidence: float
    detail: str  # matched_on (calls_service) or library (publishes/consumes)


def fetch_unconfirmed(query_runner: QueryRunner, repo_id: str) -> list[UnconfirmedLink]:
    links: list[UnconfirmedLink] = []

    for row in query_runner(
        "MATCH (a:Service)-[r:CALLS_SERVICE]->(b:Service) "
        "WHERE r.status = 'unconfirmed' AND (a.repo_id = $repo_id OR b.repo_id = $repo_id) "
        "RETURN id(r) AS rel_id, a.name AS source, a.repo_id AS source_repo_id, "
        "b.name AS target, b.repo_id AS target_repo_id, r.confidence AS confidence, r.matched_on AS matched_on",
        {"repo_id": repo_id},
    ):
        links.append(
            UnconfirmedLink(
                rel_id=row["rel_id"],
                kind="calls_service",
                source=row["source"],
                source_repo_id=row["source_repo_id"],
                target=row["target"],
                target_repo_id=row["target_repo_id"],
                confidence=row.get("confidence") or 0.0,
                detail=row.get("matched_on") or "",
            )
        )

    for row in query_runner(
        "MATCH (s:Service {repo_id: $repo_id})-[r:PUBLISHES|CONSUMES]->(e:Event) "
        "WHERE r.status = 'unconfirmed' "
        "RETURN id(r) AS rel_id, type(r) AS rel_type, s.name AS service, e.event_id AS topic, "
        "r.confidence AS confidence, r.library AS library",
        {"repo_id": repo_id},
    ):
        links.append(
            UnconfirmedLink(
                rel_id=row["rel_id"],
                kind=row["rel_type"].lower(),
                source=row["service"],
                source_repo_id=repo_id,
                target=row["topic"],
                target_repo_id=None,
                confidence=row.get("confidence") or 0.0,
                detail=row.get("library") or "",
            )
        )

    links.sort(key=lambda link: link.confidence)
    return links


def set_status(query_runner: QueryRunner, rel_id: int, status: str) -> None:
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {_STATUSES}, got {status!r}")
    query_runner("MATCH ()-[r]->() WHERE id(r) = $rel_id SET r.status = $status", {"rel_id": rel_id, "status": status})

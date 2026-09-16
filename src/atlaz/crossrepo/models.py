"""Data shapes for cross-repo service correlation.

Kept separate from `atlaz.docgen.models` even though the shape is similar:
these are heuristic, cross-repo findings (edges land with
`status="unconfirmed"` once written -- see `CrossRepoLinkService.write`),
not facts read straight off one repo's own finished graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.shared.evidence import Evidence


@dataclass(slots=True)
class OutboundCallSignal:
    """One place in a repo's source that looks like it names another
    service -- either a literal URL's host, or the name of an env var
    that plausibly holds one (`ORDER_SERVICE_URL`, `PAYMENT_SERVICE_HOST`,
    ...). `path` is empty for the env-var case, since no route is known."""

    host: str
    path: str = ""
    raw_target: str = ""  # original literal/env-var name, kept for evidence readability
    evidence: Evidence = field(default_factory=Evidence)


@dataclass(slots=True)
class ServiceLinkCandidate:
    source_repo_id: str
    source_service: str
    target_repo_id: str
    target_service: str
    matched_on: str  # "service_name_and_route" | "service_name_only"
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)


@dataclass(slots=True)
class PubSubSignal:
    """One place in a repo's source that looks like a message-queue/event-
    stream publish or consume call site -- see `atlaz.crossrepo.scanner.
    scan_pubsub_signals`'s pattern table for exactly what's matched per
    library. `topic` is the raw string captured (queue name, routing key,
    stream key, or topic/subscription name), not yet normalized."""

    direction: str  # "publish" | "consume"
    topic: str
    library: str  # "kafka" | "rabbitmq" | "sqs" | "azure_servicebus" | "redis_streams" | "google_pubsub"
    evidence: Evidence = field(default_factory=Evidence)


@dataclass(slots=True)
class PubSubFinding:
    """A `PubSubSignal` attributed to a specific `Service` in one repo,
    ready to write as a `PUBLISHES`/`CONSUMES` edge to a shared `Event`
    node. Unlike `ServiceLinkCandidate`, this never names a *target* repo --
    cross-repo linkage comes from two repos' findings landing on the same
    `Event` node (keyed by normalized topic), not from pairwise matching."""

    repo_id: str
    service: str
    direction: str
    topic: str  # normalized
    library: str
    confidence: float
    evidence: Evidence = field(default_factory=Evidence)

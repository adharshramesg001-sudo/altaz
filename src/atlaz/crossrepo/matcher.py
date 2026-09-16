"""Pure correlation logic: turns one repo's outbound-call signals into
`ServiceLinkCandidate`s against another repo's already-known facts.

No I/O here -- `atlaz.crossrepo.service` gathers the inputs (graph facts via
`atlaz.docgen.graph_facts.fetch_project_facts`, source signals via
`atlaz.crossrepo.scanner`) and this module just does the matching, so it can
be unit-tested without a database.
"""

from __future__ import annotations

from atlaz.crossrepo.attribution import normalize_name, owning_service
from atlaz.crossrepo.models import OutboundCallSignal, ServiceLinkCandidate
from atlaz.docgen.models import ProjectFacts


def _target_service_lookup(target_facts: ProjectFacts, declared_names: set[str]) -> dict[str, str]:
    """Maps a normalized candidate name -> the actual target `Service.name`
    to attach an edge to. A host string only ever resolves to the specific
    component it names. The repository name / declared docker-compose|k8s
    names are only usable as a fallback anchor when the target repo has
    exactly one `Service` -- the common case for a single-purpose
    microservice repo, where "the repo" and "the service" are the same
    thing. With multiple components in the target repo, a generic
    repo-level name can't disambiguate which one, so it's left unmapped
    (dropped by `correlate`, not guessed)."""
    lookup = {normalize_name(s.name): s.name for s in target_facts.services}
    if len(target_facts.services) == 1:
        only = target_facts.services[0].name
        lookup.setdefault(normalize_name(target_facts.repository.name), only)
        for name in declared_names:
            lookup.setdefault(normalize_name(name), only)
    return lookup


def correlate(
    source_facts: ProjectFacts,
    source_signals: list[OutboundCallSignal],
    target_facts: ProjectFacts,
    target_declared_names: set[str],
) -> list[ServiceLinkCandidate]:
    target_lookup = _target_service_lookup(target_facts, target_declared_names)
    target_routes = [api.route for api in target_facts.apis]

    candidates: list[ServiceLinkCandidate] = []
    for signal in source_signals:
        target_service = target_lookup.get(normalize_name(signal.host))
        if target_service is None:
            continue
        source_service = owning_service(signal.evidence.file, source_facts.service_files)
        if source_service is None:
            continue  # evidence file isn't attributable to any known component

        route_overlap = bool(signal.path) and any(
            signal.path.startswith(route) or route.startswith(signal.path) for route in target_routes
        )
        confidence, matched_on = (0.85, "service_name_and_route") if route_overlap else (0.55, "service_name_only")

        candidates.append(
            ServiceLinkCandidate(
                source_repo_id=source_facts.repository.repo_id,
                source_service=source_service,
                target_repo_id=target_facts.repository.repo_id,
                target_service=target_service,
                matched_on=matched_on,
                confidence=confidence,
                evidence=[signal.evidence],
            )
        )
    return candidates

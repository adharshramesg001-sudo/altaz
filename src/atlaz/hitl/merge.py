"""collect_flagged_items: merges every domain's low-confidence findings and
Domain A's gap(s) into the one `flagged_for_review` queue the three-tier
HITL gate reads. Two origins land in the same list: a Domain A gap, and any
finding below its tier's confidence threshold. Intended-vs-implemented
conflicts are handled by `atlaz.orchestration.conflicts`/`dispute_resolution`
instead (see `atlaz.hitl.models`'s module docstring for why).
"""

from __future__ import annotations

from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.agents.domain_d.security_control_scanner import SecurityControl
from atlaz.hitl.models import ReviewItem, ReviewItemKind
from atlaz.hitl.natural_keys import natural_key


def collect_flagged_items(
    *,
    flagged_gaps: list[GapFinding],
    capability_clusters: list[CapabilityCluster],
    glossary_terms: list[GlossaryTerm],
    functional_requirements: list[FunctionalRequirement],
    component_diagram: ComponentDiagram,
    security_controls: list[SecurityControl],
    confidence_threshold: float,
) -> list[ReviewItem]:
    items: list[ReviewItem] = []

    for gap in flagged_gaps:
        items.append(
            ReviewItem(
                item_id=f"domain_a::{gap.corner}",
                kind=ReviewItemKind.GAP_CONFIRMATION,
                source_domain="domain_a",
                summary="Business Case / Vision has no code signal -- external-only by definition.",
                subject=gap,
                confidence=None,
            )
        )

    for cluster in capability_clusters:
        if cluster.confidence < confidence_threshold:
            items.append(_low_confidence_item("domain_b.capability_clustering", cluster))

    for term in glossary_terms:
        if term.confidence < confidence_threshold:
            items.append(_low_confidence_item("domain_b.domain_glossary", term))

    for req in functional_requirements:
        if req.confidence < confidence_threshold:
            items.append(_low_confidence_item("domain_c.frd_extractor", req))

    if component_diagram.confidence < confidence_threshold:
        items.append(_low_confidence_item("domain_d.hld_builder", component_diagram))

    for control in security_controls:
        if control.regulation_confidence is not None and control.regulation_confidence < confidence_threshold:
            items.append(_low_confidence_item("domain_d.security_control_scanner", control))

    return items


def _low_confidence_item(source_domain: str, subject) -> ReviewItem:
    confidence = getattr(subject, "confidence", 0.0)
    key = natural_key(subject)
    return ReviewItem(
        item_id=f"low_confidence::{source_domain}::{key}",
        kind=ReviewItemKind.LOW_CONFIDENCE_FINDING,
        source_domain=source_domain,
        summary=f"{key} is below the confidence threshold ({confidence:.2f}).",
        subject=subject,
        confidence=confidence,
        natural_key=key,
    )

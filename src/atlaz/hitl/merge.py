"""collect_node (LLD Section 9): merges every domain's output into the one
`flagged_for_review` queue the consolidated HITL gate (Section 7) reads.
Three origins land in the same list: the Domain A gap, any finding below
its tier's confidence threshold, and any rule/entity conflict.
"""

from __future__ import annotations

from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.api_contract_parser import APIContract
from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.agents.domain_d.security_control_scanner import SecurityControl
from atlaz.hitl.conflict_detection import find_conflicts
from atlaz.hitl.models import ReviewItem, ReviewItemKind


def collect_flagged_items(
    *,
    gap_finding: GapFinding,
    capability_clusters: list[CapabilityCluster],
    business_rules: list[BusinessRule],
    glossary_terms: list[GlossaryTerm],
    functional_requirements: list[FunctionalRequirement],
    component_diagram: ComponentDiagram,
    data_entities: list[DataEntity],
    api_contracts: list[APIContract],
    security_controls: list[SecurityControl],
    confidence_threshold: float,
) -> list[ReviewItem]:
    items: list[ReviewItem] = []

    items.append(
        ReviewItem(
            item_id="domain_a::business_case_vision",
            kind=ReviewItemKind.GAP_CONFIRMATION,
            source_domain="domain_a",
            summary="Business Case / Vision has no code signal -- external-only by definition.",
            subject=gap_finding,
            confidence=None,
        )
    )

    for cluster in capability_clusters:
        if cluster.confidence < confidence_threshold:
            items.append(_low_confidence_item("domain_b.capability_clustering", cluster.capability_name, cluster))

    for term in glossary_terms:
        if term.confidence < confidence_threshold:
            items.append(_low_confidence_item("domain_b.domain_glossary", term.term, term))

    for req in functional_requirements:
        if req.confidence < confidence_threshold:
            items.append(_low_confidence_item("domain_c.frd_extractor", req.function_ref, req))

    if component_diagram.confidence < confidence_threshold:
        items.append(
            _low_confidence_item(
                "domain_d.hld_builder", f"architecture_style={component_diagram.architecture_style}", component_diagram
            )
        )

    for control in security_controls:
        if control.regulation_confidence is not None and control.regulation_confidence < confidence_threshold:
            items.append(
                _low_confidence_item(
                    "domain_d.security_control_scanner",
                    f"regulation_hypothesis for {control.location}",
                    control,
                )
            )

    for conflict in find_conflicts(business_rules, data_entities):
        items.append(
            ReviewItem(
                item_id=f"conflict::{conflict.business_rule.rule_id}::{conflict.data_entity.entity_name}::{conflict.field_name}",
                kind=ReviewItemKind.CONFLICT,
                source_domain="merge.conflict_detection",
                summary=(
                    f"'{conflict.business_rule.rule_id}' says {conflict.rule_value}, but "
                    f"{conflict.data_entity.entity_name}.{conflict.field_name} implements {conflict.entity_value}."
                ),
                subject=conflict,
                confidence=None,
            )
        )

    return items


def _low_confidence_item(source_domain: str, label: str, subject) -> ReviewItem:
    confidence = getattr(subject, "confidence", 0.0)
    return ReviewItem(
        item_id=f"low_confidence::{source_domain}::{label}",
        kind=ReviewItemKind.LOW_CONFIDENCE_FINDING,
        source_domain=source_domain,
        summary=f"{label} is below the confidence threshold ({confidence:.2f}).",
        subject=subject,
        confidence=confidence,
    )

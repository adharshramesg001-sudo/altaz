"""Translates every domain agent's dataclass output into the `GraphNode`/
`GraphEdge` batch `Neo4jWriter` commits (LLD Section 9's `graph_write_batch`,
Section 11's schema).

Implementation note on Evidence: the LLD's Section 11 schema lists `Evidence`
as its own node label with a `documents` edge into whatever it backs. This
builder instead serializes each finding's `evidence` list as a JSON property
on the finding's own node (`evidence_json`). Every fact stays exactly as
traceable -- file/line/commit are still on the node -- without one
graph write per citation for high-volume corners like BusinessRule and
GlossaryTerm, whose evidence lists can run into the dozens. `conflicts_with`
is deliberately absent here: the LLD requires it to be created only after a
human resolution record exists (Section 11), so it is added later by the
HITL/merge layer, never by this translation step.
"""

from __future__ import annotations

import json

from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.api_contract_parser import APIContract
from atlaz.agents.domain_d.data_model_extractor import DataEntity, DataModelExtractor
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.agents.domain_d.security_control_scanner import SecurityControl
from atlaz.graph_store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from atlaz.hitl.conflict_detection import ConflictCandidate
from atlaz.hitl.models import ReviewAction, ReviewResolution
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier


def _evidence_json(evidence: list[Evidence]) -> str:
    return json.dumps([e.to_dict() for e in evidence])


def _base_properties(tier: Tier, confidence: float, evidence: list[Evidence], confidence_threshold: float) -> dict:
    return {
        "tier": tier.value,
        "confidence": confidence,
        "needs_review": confidence < confidence_threshold,
        "evidence_json": _evidence_json(evidence),
    }


def build_capability_nodes(clusters: list[CapabilityCluster], confidence_threshold: float) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.CAPABILITY,
            key_value=c.capability_name,
            properties={
                "cohesion_score": c.cohesion_score,
                "member_modules": list(c.member_modules),
                **_base_properties(c.tier, c.confidence, c.evidence, confidence_threshold),
            },
        )
        for c in clusters
    ]


def build_business_rule_nodes(rules: list[BusinessRule], confidence_threshold: float) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.BUSINESS_RULE,
            key_value=r.rule_id,
            properties={
                "description": r.description,
                "literal_value": r.literal_value,
                "source_kind": r.source_kind,
                **_base_properties(r.tier, r.confidence, r.evidence, confidence_threshold),
            },
        )
        for r in rules
    ]


def build_requirement_nodes(requirements: list[FunctionalRequirement], confidence_threshold: float) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.REQUIREMENT,
            key_value=r.function_ref,
            properties={
                "signature": r.signature,
                "inferred_behavior": r.inferred_behavior,
                **_base_properties(r.tier, r.confidence, r.evidence, confidence_threshold),
            },
        )
        for r in requirements
    ]


def build_test_case_nodes_and_edges(requirements: list[FunctionalRequirement]) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: dict[str, GraphNode] = {}
    edges: list[GraphEdge] = []
    for req in requirements:
        for test_name in req.supporting_tests:
            if test_name not in nodes:
                file_path = test_name.rsplit(".", 1)[0].replace(".", "/") + ".py"
                nodes[test_name] = GraphNode(
                    label=NodeLabel.TEST_CASE, key_value=test_name, properties={"file_path": file_path}
                )
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.VALIDATES,
                    source_label=NodeLabel.TEST_CASE,
                    source_key=test_name,
                    target_label=NodeLabel.REQUIREMENT,
                    target_key=req.function_ref,
                )
            )
    return list(nodes.values()), edges


def build_component_nodes_and_edges(diagram: ComponentDiagram) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes = [
        GraphNode(
            label=NodeLabel.COMPONENT,
            key_value=c.name,
            properties={"architecture_style": diagram.architecture_style, "module_count": len(c.module_paths)},
        )
        for c in diagram.components
    ]
    edges = [
        GraphEdge(
            edge_type=EdgeType.DEPENDS_ON,
            source_label=NodeLabel.COMPONENT,
            source_key=e.source_component,
            target_label=NodeLabel.COMPONENT,
            target_key=e.target_component,
            properties={"call_count": e.call_count},
        )
        for e in diagram.edges
    ]
    return nodes, edges


def build_module_nodes(parsed: list[ParsedModule]) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.MODULE,
            key_value=m.file_path,
            properties={
                "language": m.language,
                "parse_depth": m.parse_depth.value,
                "function_count": len(m.functions),
                "class_count": len(m.classes),
            },
        )
        for m in parsed
    ]


def build_data_entity_nodes_and_edges(
    entities: list[DataEntity], confidence_threshold: float
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes = [
        GraphNode(
            label=NodeLabel.DATA_ENTITY,
            key_value=e.entity_name,
            properties={
                "source_kind": e.source_kind,
                "fields_json": json.dumps(
                    [{"name": f.name, "type": f.field_type, "default": f.default_value} for f in e.fields]
                ),
                **_base_properties(e.tier, e.confidence, e.evidence, confidence_threshold),
            },
        )
        for e in entities
    ]
    edges = []
    for entity in entities:
        for rel in entity.relationships:
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.DEPENDS_ON,
                    source_label=NodeLabel.DATA_ENTITY,
                    source_key=rel.from_entity,
                    target_label=NodeLabel.DATA_ENTITY,
                    target_key=rel.to_entity,
                    properties={"kind": rel.kind},
                )
            )
    for from_name, to_name in DataModelExtractor.entity_derivation_edges(entities):
        edges.append(
            GraphEdge(
                edge_type=EdgeType.DERIVED_FROM,
                source_label=NodeLabel.DATA_ENTITY,
                source_key=from_name,
                target_label=NodeLabel.DATA_ENTITY,
                target_key=to_name,
            )
        )
    return nodes, edges


def build_api_contract_nodes(contracts: list[APIContract], confidence_threshold: float) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.API_CONTRACT,
            key_value=f"{c.route}::{c.method}",
            properties={
                "route": c.route,
                "method": c.method,
                "handler_ref": c.handler_ref,
                "source_kind": c.source_kind,
                **_base_properties(c.tier, c.confidence, c.evidence, confidence_threshold),
            },
        )
        for c in contracts
    ]


def build_security_control_nodes(controls: list[SecurityControl], confidence_threshold: float) -> list[GraphNode]:
    nodes = []
    for c in controls:
        control_id = f"{c.control_type}::{c.location}::{c.detail}"[:512]
        nodes.append(
            GraphNode(
                label=NodeLabel.SECURITY_CONTROL,
                key_value=control_id,
                properties={
                    "control_type": c.control_type,
                    "location": c.location,
                    "detail": c.detail,
                    "regulation_hypothesis": c.regulation_hypothesis,
                    "regulation_confidence": c.regulation_confidence,
                    **_base_properties(c.tier, c.confidence, c.evidence, confidence_threshold),
                },
            )
        )
    return nodes


def build_glossary_term_nodes(terms: list[GlossaryTerm], confidence_threshold: float) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.GLOSSARY_TERM,
            key_value=t.term,
            properties={
                "definition": t.definition,
                "occurrence_count": t.occurrence_count,
                "source_kinds": list(t.source_kinds),
                **_base_properties(t.tier, t.confidence, t.evidence, confidence_threshold),
            },
        )
        for t in terms
    ]


def build_gap_node(finding: GapFinding, resolution: ReviewResolution | None = None) -> GraphNode:
    """A human-supplied answer (`resolution.action` ACCEPT/EDIT with a
    non-empty `resolved_value`) fills `resolution_answer`; anything else --
    no resolution, a REJECT ("no info available"), or the auto-resolve
    policy's fixed "unknown" note -- leaves the gap open. Either way
    `tier` stays EXTERNAL_ONLY: a human confirming a gap is not the same as
    code newly making it extractable."""
    resolution_answer = None
    if resolution is not None and resolution.action in (ReviewAction.ACCEPT, ReviewAction.EDIT):
        resolution_answer = resolution.resolved_value
    return GraphNode(
        label=NodeLabel.GAP,
        key_value=finding.corner,
        properties={
            "tier": finding.tier.value,
            "signal_found": finding.signal_found,
            "candidate_signals_json": json.dumps(
                [{"source_kind": s.source_kind, "text": s.text, **s.evidence.to_dict()} for s in finding.candidate_signals]
            ),
            "evidence_json": _evidence_json(finding.evidence),
            "routed_to": finding.routed_to,
            "resolution_answer": resolution_answer,
            "still_open": resolution_answer is None,
        },
    )


def build_capability_ownership_edges(
    clusters: list[CapabilityCluster], entities: list[DataEntity], contracts: list[APIContract]
) -> list[GraphEdge]:
    """`owns` edges: Capability -> DataEntity / APIContract, linked by
    whether the entity/contract's evidence file is one of the capability's
    member modules (LLD Section 11 relationship semantics)."""
    edges: list[GraphEdge] = []
    for cluster in clusters:
        member_set = set(cluster.member_modules)
        for entity in entities:
            if any(e.file in member_set for e in entity.evidence if e.file):
                edges.append(
                    GraphEdge(
                        edge_type=EdgeType.OWNS,
                        source_label=NodeLabel.CAPABILITY,
                        source_key=cluster.capability_name,
                        target_label=NodeLabel.DATA_ENTITY,
                        target_key=entity.entity_name,
                    )
                )
        for contract in contracts:
            if any(e.file in member_set for e in contract.evidence if e.file):
                edges.append(
                    GraphEdge(
                        edge_type=EdgeType.OWNS,
                        source_label=NodeLabel.CAPABILITY,
                        source_key=cluster.capability_name,
                        target_label=NodeLabel.API_CONTRACT,
                        target_key=f"{contract.route}::{contract.method}",
                    )
                )
    return edges


def build_component_implements_capability_edges(
    diagram: ComponentDiagram, clusters: list[CapabilityCluster]
) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for component in diagram.components:
        component_modules = set(component.module_paths)
        for cluster in clusters:
            overlap = component_modules & set(cluster.member_modules)
            if overlap:
                edges.append(
                    GraphEdge(
                        edge_type=EdgeType.IMPLEMENTS,
                        source_label=NodeLabel.COMPONENT,
                        source_key=component.name,
                        target_label=NodeLabel.CAPABILITY,
                        target_key=cluster.capability_name,
                        properties={"shared_module_count": len(overlap)},
                    )
                )
    return edges


def build_conflict_edges(resolutions: list[ReviewResolution]) -> list[GraphEdge]:
    """`conflicts_with` edges (LLD Section 11): the only edge type ever
    written exclusively post-HITL. Every RESOLVE_CONFLICT resolution carries
    the original `ConflictCandidate` as `resolved_value` -- whether a human
    picked a side or the auto-resolve policy left it unresolved -- so both
    sides are always recorded; `resolution_note` is what distinguishes the
    two cases downstream."""
    edges: list[GraphEdge] = []
    for resolution in resolutions:
        if resolution.action != ReviewAction.RESOLVE_CONFLICT or resolution.resolved_value is None:
            continue
        candidate: ConflictCandidate = resolution.resolved_value
        edges.append(
            GraphEdge(
                edge_type=EdgeType.CONFLICTS_WITH,
                source_label=NodeLabel.BUSINESS_RULE,
                source_key=candidate.business_rule.rule_id,
                target_label=NodeLabel.DATA_ENTITY,
                target_key=candidate.data_entity.entity_name,
                properties={
                    "field_name": candidate.field_name,
                    "rule_value": candidate.rule_value,
                    "entity_value": candidate.entity_value,
                    "resolved_by": resolution.reviewer,
                    "resolution_note": resolution.resolution_note,
                    "unresolved": resolution.resolution_note.startswith("left unresolved"),
                },
            )
        )
    return edges


def build_module_implements_requirement_edges(requirements: list[FunctionalRequirement]) -> list[GraphEdge]:
    edges = []
    for req in requirements:
        if not req.evidence:
            continue
        module_path = req.evidence[0].file
        if not module_path:
            continue
        edges.append(
            GraphEdge(
                edge_type=EdgeType.IMPLEMENTS,
                source_label=NodeLabel.MODULE,
                source_key=module_path,
                target_label=NodeLabel.REQUIREMENT,
                target_key=req.function_ref,
            )
        )
    return edges

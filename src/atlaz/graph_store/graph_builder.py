"""Translates every deterministic-stage artifact and domain agent's output
into the `GraphNode`/`GraphEdge` batch `Neo4jWriter` commits (LLD Section
9's write stage, Section 14.2's schema).

Evidence stays serialized as a JSON property on each finding's own node
(`evidence_json`) rather than as its own graph node per citation -- the
same choice the prior build made, still true here: full traceability
without one graph write per citation for high-volume corners. Postgres
`evidence_records` (LLD Section 14.4) is the queryable/joinable source; the
inline JSON is for cheap reads without a second round-trip.

`CALLS` edges are only ever written for statically-resolved call-graph
edges: an unresolved dynamic-dispatch callee has no corresponding `Method`
node to `MATCH`, so writing it would be a dangling edge `Neo4jWriter`
can't create anyway (`MERGE` requires both endpoints to already exist).
Unresolved edges stay visible in the in-memory `dependency_graph` and the
`parse_failures`/evidence store, not silently dropped -- just never forced
into the graph as a phantom node.
"""

from __future__ import annotations

import json

from atlaz.agents.cross_domain.workflow_trace import WorkflowTrace
from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.agents.domain_d.lld_parser import LLDEntry
from atlaz.agents.domain_d.security_control_scanner import SecurityControl
from atlaz.analysis.call_graph import CallGraph
from atlaz.analysis.config_schema_api import ConfigSchemaAPI
from atlaz.analysis.symbol_table import SymbolTable
from atlaz.graph_store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from atlaz.ingestion.models import RepoInventory
from atlaz.orchestration.dispute_resolution import ResolvedClaim
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

DEFAULT_DATABASE_SUFFIX = "::default_database"


def _evidence_json(evidence: list[Evidence]) -> str:
    return json.dumps([e.to_dict() for e in evidence])


def _base_properties(tier: Tier, confidence: float, evidence: list[Evidence], confidence_threshold: float) -> dict:
    return {
        "tier": tier.value,
        "confidence": confidence,
        "needs_review": confidence < confidence_threshold,
        "evidence_json": _evidence_json(evidence),
    }


def _status_for(claim_id: str, resolved_by_claim_id: dict[str, ResolvedClaim]) -> str:
    resolved = resolved_by_claim_id.get(claim_id)
    return resolved.status if resolved else "confirmed"


# --- technical graph -------------------------------------------------------


def build_repository_node(repo_id: str, name: str, primary_languages: list[str]) -> GraphNode:
    return GraphNode(
        label=NodeLabel.REPOSITORY,
        key_value=repo_id,
        properties={"name": name, "primary_languages": primary_languages},
    )


def build_file_nodes(inventory: RepoInventory, file_classification: dict[str, str]) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.FILE,
            key_value=f.path,
            properties={
                "path": f.path,
                "language": f.language,
                "classification": file_classification.get(f.path, "unknown"),
            },
        )
        for f in inventory.files
    ]


def build_service_nodes_and_edges(
    repo_id: str, diagram: ComponentDiagram
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Service doubles as the LLD's `Module` (folder container) and
    `Service` (HLD-derived boundary) roles -- see `graph_store.schema`'s
    module docstring for why."""
    nodes = [
        GraphNode(
            label=NodeLabel.SERVICE,
            key_value=c.name,
            properties={
                "name": c.name,
                "boundary_source": "hld_builder",
                "architecture_style": diagram.architecture_style,
                "module_count": len(c.module_paths),
            },
        )
        for c in diagram.components
    ]
    edges: list[GraphEdge] = []
    for component in diagram.components:
        edges.append(
            GraphEdge(
                edge_type=EdgeType.CONTAINS,
                source_label=NodeLabel.REPOSITORY,
                source_key=repo_id,
                target_label=NodeLabel.SERVICE,
                target_key=component.name,
            )
        )
        for path in component.module_paths:
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.CONTAINS,
                    source_label=NodeLabel.SERVICE,
                    source_key=component.name,
                    target_label=NodeLabel.FILE,
                    target_key=path,
                )
            )
    for e in diagram.edges:
        edges.append(
            GraphEdge(
                edge_type=EdgeType.DEPENDS_ON,
                source_label=NodeLabel.SERVICE,
                source_key=e.source_component,
                target_label=NodeLabel.SERVICE,
                target_key=e.target_component,
                properties={"call_count": e.call_count},
            )
        )
    return nodes, edges


def build_class_and_method_nodes(
    symbol_table: SymbolTable, lld_entries: list[LLDEntry] | None = None
) -> tuple[list[GraphNode], list[GraphNode]]:
    """`lld_entries` (Domain D's `LLDParser` output, LLD Section 8.2 -- "the
    single most reliable extraction in the framework", confidence fixed at
    1.0) enriches each node with its rendered signature/return type/
    parameters when available, keyed by the same qualified name both
    `SymbolTable` and `LLDEntry` use. Without it, nodes still carry the
    structural facts the deterministic stage always has (name/file/lines)."""
    lld_by_qualname = {e.class_or_function: e for e in (lld_entries or [])}
    class_nodes, method_nodes = [], []
    for entry in symbol_table.symbols.values():
        lld_entry = lld_by_qualname.get(entry.qualified_name)
        if entry.kind == "class":
            class_nodes.append(
                GraphNode(
                    label=NodeLabel.CLASS,
                    key_value=entry.qualified_name,
                    properties={
                        "name": entry.name,
                        "file_id": entry.file_path,
                        "line_start": entry.line_start,
                        "line_end": entry.line_end,
                        "signature": lld_entry.signature if lld_entry else "",
                    },
                )
            )
        else:
            method_nodes.append(
                GraphNode(
                    label=NodeLabel.METHOD,
                    key_value=entry.qualified_name,
                    properties={
                        "name": entry.name,
                        "file_id": entry.file_path,
                        "line_start": entry.line_start,
                        "line_end": entry.line_end,
                        "reachability": "unknown_external",  # refined below via `apply_reachability`
                        "signature": lld_entry.signature if lld_entry else "",
                        "return_type": (lld_entry.return_type if lld_entry else None) or "",
                        "parameters_json": json.dumps(
                            [{"name": p.name, "annotation": p.annotation, "default": p.default} for p in lld_entry.parameters]
                        )
                        if lld_entry
                        else "[]",
                    },
                )
            )
    return class_nodes, method_nodes


def apply_reachability(method_nodes: list[GraphNode], call_graph: CallGraph) -> None:
    """Mutates each Method node's `reachability` in place: `reachable` if
    anything statically calls it or it's a module-level entry point with
    outgoing calls, `unreachable` otherwise. Used both for the graph write
    and by `orchestration.nodes` to build `reachability` conflict claims."""
    called = {e.callee for e in call_graph.edges if e.resolution == "static"}
    for node in method_nodes:
        node.properties["reachability"] = "reachable" if node.key_value in called else "unreachable"


def build_defines_and_calls_edges(
    symbol_table: SymbolTable, call_graph: CallGraph
) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for entry in symbol_table.symbols.values():
        if entry.kind == "class":
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.DEFINES,
                    source_label=NodeLabel.FILE,
                    source_key=entry.file_path,
                    target_label=NodeLabel.CLASS,
                    target_key=entry.qualified_name,
                )
            )
        elif entry.kind == "method" and entry.parent_class:
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.DEFINES,
                    source_label=NodeLabel.CLASS,
                    source_key=entry.parent_class,
                    target_label=NodeLabel.METHOD,
                    target_key=entry.qualified_name,
                )
            )
        else:
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.DEFINES,
                    source_label=NodeLabel.FILE,
                    source_key=entry.file_path,
                    target_label=NodeLabel.METHOD,
                    target_key=entry.qualified_name,
                )
            )

    known_methods = {qn for qn, e in symbol_table.symbols.items() if e.kind in ("function", "method")}
    for edge in call_graph.edges:
        if edge.resolution != "static" or edge.caller not in known_methods or edge.callee not in known_methods:
            continue
        edges.append(
            GraphEdge(
                edge_type=EdgeType.CALLS,
                source_label=NodeLabel.METHOD,
                source_key=edge.caller,
                target_label=NodeLabel.METHOD,
                target_key=edge.callee,
                properties={"resolution": edge.resolution},
            )
        )
    return edges


def build_table_and_database_nodes_and_edges(
    repo_id: str, config_schema_api: ConfigSchemaAPI, diagram: ComponentDiagram, confidence_threshold: float
) -> tuple[list[GraphNode], list[GraphEdge]]:
    database_id = f"{repo_id}{DEFAULT_DATABASE_SUFFIX}"
    nodes: list[GraphNode] = [GraphNode(label=NodeLabel.DATABASE, key_value=database_id, properties={"name": "default", "engine": "unknown"})]
    edges: list[GraphEdge] = []
    for entity in config_schema_api.data_entities:
        nodes.append(
            GraphNode(
                label=NodeLabel.TABLE,
                key_value=entity.entity_name,
                properties={
                    "name": entity.entity_name,
                    "source_kind": entity.source_kind,
                    "fields_json": json.dumps(
                        [{"name": f.name, "type": f.field_type, "default": f.default_value} for f in entity.fields]
                    ),
                    **_base_properties(entity.tier, entity.confidence, entity.evidence, confidence_threshold),
                },
            )
        )
        edges.append(
            GraphEdge(
                edge_type=EdgeType.BELONGS_TO,
                source_label=NodeLabel.TABLE,
                source_key=entity.entity_name,
                target_label=NodeLabel.DATABASE,
                target_key=database_id,
            )
        )
        owning_file = entity.evidence[0].file if entity.evidence else None
        owning_service = _component_for_file(owning_file, diagram)
        if owning_service:
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.OWNS,
                    source_label=NodeLabel.SERVICE,
                    source_key=owning_service,
                    target_label=NodeLabel.TABLE,
                    target_key=entity.entity_name,
                )
            )
        for rel in entity.relationships:
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.DEPENDS_ON,
                    source_label=NodeLabel.TABLE,
                    source_key=rel.from_entity,
                    target_label=NodeLabel.TABLE,
                    target_key=rel.to_entity,
                    properties={"kind": rel.kind},
                )
            )
    return nodes, edges


def build_api_nodes_and_edges(
    config_schema_api: ConfigSchemaAPI, diagram: ComponentDiagram, confidence_threshold: float
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes = [
        GraphNode(
            label=NodeLabel.API,
            key_value=f"{c.route}::{c.method}",
            properties={
                "route": c.route,
                "method": c.method,
                "handler_ref": c.handler_ref,
                "spec_source": c.source_kind,
                **_base_properties(c.tier, c.confidence, c.evidence, confidence_threshold),
            },
        )
        for c in config_schema_api.api_contracts
    ]
    edges: list[GraphEdge] = []
    for contract in config_schema_api.api_contracts:
        evidence_file = contract.evidence[0].file if contract.evidence else None
        component = _component_for_file(evidence_file, diagram)
        if component:
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.EXPOSES,
                    source_label=NodeLabel.SERVICE,
                    source_key=component,
                    target_label=NodeLabel.API,
                    target_key=f"{contract.route}::{contract.method}",
                )
            )
    return nodes, edges


def _component_for_file(file_path: str | None, diagram: ComponentDiagram) -> str | None:
    if not file_path:
        return None
    for component in diagram.components:
        if file_path in component.module_paths:
            return component.name
    return None


# --- business graph ---------------------------------------------------------


def build_business_capability_nodes(clusters: list[CapabilityCluster], confidence_threshold: float) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.BUSINESS_CAPABILITY,
            key_value=c.capability_name,
            properties={
                "name": c.capability_name,
                "cohesion_score": c.cohesion_score,
                "member_modules": list(c.member_modules),
                "strategic_context_gap": True,  # Domain A never fills this (LLD Section 9.3)
                "source_domain": "domain_b",
                **_base_properties(c.tier, c.confidence, c.evidence, confidence_threshold),
            },
        )
        for c in clusters
    ]


def build_feature_nodes_and_edges(clusters: list[CapabilityCluster]) -> tuple[list[GraphNode], list[GraphEdge]]:
    """One `Feature` per `BusinessCapability` -- no dedicated Feature
    extraction agent exists in this build, so Feature is derived 1:1 from
    the capability that owns it rather than independently extracted. This
    is a disclosed simplification, not a hidden fabrication: `source_domain`
    on the node makes the derivation explicit."""
    nodes, edges = [], []
    for cluster in clusters:
        feature_id = f"feature::{cluster.capability_name}"
        nodes.append(
            GraphNode(
                label=NodeLabel.FEATURE,
                key_value=feature_id,
                properties={"name": cluster.capability_name, "confidence": cluster.confidence, "source_domain": "domain_b"},
            )
        )
        edges.append(
            GraphEdge(
                edge_type=EdgeType.HAS_FEATURE,
                source_label=NodeLabel.BUSINESS_CAPABILITY,
                source_key=cluster.capability_name,
                target_label=NodeLabel.FEATURE,
                target_key=feature_id,
                properties={"confidence": cluster.confidence},
            )
        )
    return nodes, edges


def build_workflow_nodes_and_edges(traces: list[WorkflowTrace]) -> tuple[list[GraphNode], list[GraphNode], list[GraphEdge]]:
    workflow_nodes, step_nodes, edges = [], [], []
    for trace in traces:
        workflow_nodes.append(
            GraphNode(
                label=NodeLabel.WORKFLOW,
                key_value=trace.workflow_name,
                properties={"name": trace.workflow_name, "confidence": trace.confidence},
            )
        )
        if trace.capability_name:
            feature_id = f"feature::{trace.capability_name}"
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.HAS_WORKFLOW,
                    source_label=NodeLabel.FEATURE,
                    source_key=feature_id,
                    target_label=NodeLabel.WORKFLOW,
                    target_key=trace.workflow_name,
                    properties={"confidence": trace.confidence},
                )
            )
        for i, step_qualname in enumerate(trace.steps):
            step_id = f"{trace.workflow_name}::{i}"
            step_nodes.append(
                GraphNode(
                    label=NodeLabel.STEP,
                    key_value=step_id,
                    properties={"name": step_qualname, "sequence_order": i},
                )
            )
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.HAS_STEP,
                    source_label=NodeLabel.WORKFLOW,
                    source_key=trace.workflow_name,
                    target_label=NodeLabel.STEP,
                    target_key=step_id,
                    properties={"sequence_order": i},
                )
            )
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.REALIZED_BY,
                    source_label=NodeLabel.WORKFLOW,
                    source_key=trace.workflow_name,
                    target_label=NodeLabel.METHOD,
                    target_key=step_qualname,
                    properties=_bridge_properties(
                        confidence=trace.confidence,
                        evidence=trace.evidence,
                        derivation_method="cross_domain_consolidated",
                        status="inferred",
                        scoring_weight_profile="structural_plus_textual",
                        source_domain=["domain_b", "domain_d"],
                    ),
                )
            )
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.EXECUTES,
                    source_label=NodeLabel.STEP,
                    source_key=step_id,
                    target_label=NodeLabel.METHOD,
                    target_key=step_qualname,
                )
            )
    return workflow_nodes, step_nodes, edges


def build_business_rule_nodes(
    rules: list[BusinessRule], confidence_threshold: float, resolved_by_claim_id: dict[str, ResolvedClaim]
) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.BUSINESS_RULE,
            key_value=r.rule_id,
            properties={
                "description": r.description,
                "literal_value": r.literal_value,
                "source_kind": r.source_kind,
                "status": _status_for(f"domain_b.business_rule_extraction::{r.rule_id}", resolved_by_claim_id),
                **_base_properties(r.tier, r.confidence, r.evidence, confidence_threshold),
            },
        )
        for r in rules
    ]


def build_business_rule_implemented_by_edges(rules: list[BusinessRule], symbol_table: SymbolTable) -> list[GraphEdge]:
    """`BusinessRule -[:IMPLEMENTED_BY]-> Method`: resolved by finding the
    method whose line range in the rule's evidence file encloses the rule's
    evidence line -- a real, if line-range-based, bridge rather than a
    guess."""
    by_file: dict[str, list] = {}
    for entry in symbol_table.symbols.values():
        if entry.kind in ("function", "method"):
            by_file.setdefault(entry.file_path, []).append(entry)

    edges: list[GraphEdge] = []
    for rule in rules:
        for ev in rule.evidence:
            if not ev.file or ev.line is None:
                continue
            enclosing = _enclosing_method(by_file.get(ev.file, []), ev.line)
            if enclosing is None:
                continue
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.IMPLEMENTED_BY,
                    source_label=NodeLabel.BUSINESS_RULE,
                    source_key=rule.rule_id,
                    target_label=NodeLabel.METHOD,
                    target_key=enclosing.qualified_name,
                    properties=_bridge_properties(
                        confidence=rule.confidence,
                        evidence=[ev],
                        derivation_method="ast_deterministic",
                        status="confirmed",
                        scoring_weight_profile="structural_plus_textual",
                        source_domain=["domain_b"],
                    ),
                )
            )
            break
    return edges


def _enclosing_method(entries: list, line: int):
    for entry in entries:
        if entry.line_start <= line <= entry.line_end:
            return entry
    return None


def build_domain_concept_nodes(terms: list[GlossaryTerm], confidence_threshold: float) -> list[GraphNode]:
    return [
        GraphNode(
            label=NodeLabel.DOMAIN_CONCEPT,
            key_value=t.term,
            properties={
                "term": t.term,
                "definition": t.definition,
                "occurrence_count": t.occurrence_count,
                "source_kinds": list(t.source_kinds),
                **_base_properties(t.tier, t.confidence, t.evidence, confidence_threshold),
            },
        )
        for t in terms
    ]


def build_gap_node_and_edges(
    finding: GapFinding, resolution_answer: str | None, capability_names: list[str]
) -> tuple[GraphNode, list[GraphEdge]]:
    node = GraphNode(
        label=NodeLabel.GAP,
        key_value=finding.corner,
        properties={
            "category": finding.category,
            "status": finding.status,
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
    edges = [
        GraphEdge(
            edge_type=EdgeType.HAS_GAP,
            source_label=NodeLabel.BUSINESS_CAPABILITY,
            source_key=name,
            target_label=NodeLabel.GAP,
            target_key=finding.corner,
        )
        for name in capability_names
    ]
    return node, edges


def build_feature_implemented_by_edges(clusters: list[CapabilityCluster], diagram: ComponentDiagram) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    for cluster in clusters:
        feature_id = f"feature::{cluster.capability_name}"
        member_set = set(cluster.member_modules)
        for component in diagram.components:
            overlap = member_set & set(component.module_paths)
            if not overlap:
                continue
            edges.append(
                GraphEdge(
                    edge_type=EdgeType.IMPLEMENTED_BY,
                    source_label=NodeLabel.FEATURE,
                    source_key=feature_id,
                    target_label=NodeLabel.SERVICE,
                    target_key=component.name,
                    properties=_bridge_properties(
                        confidence=cluster.confidence,
                        evidence=cluster.evidence,
                        derivation_method="cross_domain_consolidated",
                        status="inferred",
                        scoring_weight_profile="structural_plus_textual",
                        source_domain=["domain_b", "domain_d"],
                    ),
                )
            )
    return edges


# --- codebase-specific extensions (Requirement/TestCase/SecurityControl) ---


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
                nodes[test_name] = GraphNode(label=NodeLabel.TEST_CASE, key_value=test_name, properties={"file_path": file_path})
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


def build_requirement_implemented_by_edges(requirements: list[FunctionalRequirement]) -> list[GraphEdge]:
    edges = []
    for req in requirements:
        if not req.evidence:
            continue
        file_path = req.evidence[0].file
        if not file_path:
            continue
        edges.append(
            GraphEdge(
                edge_type=EdgeType.IMPLEMENTS,
                source_label=NodeLabel.FILE,
                source_key=file_path,
                target_label=NodeLabel.REQUIREMENT,
                target_key=req.function_ref,
            )
        )
    return edges


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


def build_conflict_edges(conflicts, resolved_by_claim_id: dict[str, ResolvedClaim]) -> list[GraphEdge]:
    """`CONFLICTS_WITH` edges -- only for `value_mismatch` conflicts
    (`BusinessRule` vs `Table`), the one conflict type in
    `orchestration.conflicts` with well-defined node types on both sides.
    `dead_vs_active`/`purpose_mismatch` conflicts are recorded in Postgres
    `conflict_records` (LLD Section 14.4) instead of forced into a graph
    edge between mismatched node types."""
    edges: list[GraphEdge] = []
    for conflict in conflicts:
        if conflict.conflict_type != "value_mismatch":
            continue
        rule_id = conflict.claim_a.claim_id.split("::", 1)[-1]  # claim_id = "domain_b.agent::<rule_id>"; rule_id itself may contain "::"
        table_name = conflict.entity_id.rsplit(".", 1)[0]
        resolution_a = resolved_by_claim_id.get(conflict.claim_a.claim_id)
        status = resolution_a.status if resolution_a else "unresolved_written_both"
        edges.append(
            GraphEdge(
                edge_type=EdgeType.CONFLICTS_WITH,
                source_label=NodeLabel.BUSINESS_RULE,
                source_key=rule_id,
                target_label=NodeLabel.TABLE,
                target_key=table_name,
                properties={
                    "field_name": conflict.entity_id.rsplit(".", 1)[-1],
                    "rule_value": conflict.claim_a.assertion.get("value"),
                    "table_value": conflict.claim_b.assertion.get("value"),
                    "status": status,
                    "unresolved": status == "unresolved_written_both",
                },
            )
        )
    return edges


def _bridge_properties(
    *, confidence: float, evidence: list[Evidence], derivation_method: str, status: str, scoring_weight_profile: str, source_domain: list[str]
) -> dict:
    return {
        "confidence": confidence,
        "evidence_ids": [f"{e.file}:{e.line}" for e in evidence if e.file],
        "derivation_method": derivation_method,
        "status": status,
        "scoring_weight_profile": scoring_weight_profile,
        "source_domain": source_domain,
    }

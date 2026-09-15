from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_d.api_contract_parser import APIContract
from atlaz.agents.domain_d.data_model_extractor import DataEntity, EntityRelationship, FieldInfo
from atlaz.agents.domain_d.hld_builder import Component, ComponentDiagram, DependsOnEdge
from atlaz.graph_store.graph_builder import (
    build_business_rule_nodes,
    build_capability_ownership_edges,
    build_component_implements_capability_edges,
    build_component_nodes_and_edges,
    build_conflict_edges,
    build_data_entity_nodes_and_edges,
)
from atlaz.graph_store.schema import EdgeType, NodeLabel
from atlaz.hitl.conflict_detection import ConflictCandidate
from atlaz.hitl.models import ReviewAction, ReviewResolution
from atlaz.shared.evidence import Evidence


def test_business_rule_nodes_carry_tier_confidence_and_evidence():
    rule = BusinessRule(
        rule_id="billing.py::LATE_FEE_RATE",
        description="Late fee percentage.",
        literal_value="0.045",
        source_kind="code_literal",
        evidence=[Evidence(file="billing.py", line=3)],
    )
    nodes = build_business_rule_nodes([rule], confidence_threshold=0.6)
    assert len(nodes) == 1
    node = nodes[0]
    assert node.label == NodeLabel.BUSINESS_RULE
    assert node.key_value == "billing.py::LATE_FEE_RATE"
    assert node.properties["tier"] == "extractable"
    assert node.properties["literal_value"] == "0.045"
    assert "billing.py" in node.properties["evidence_json"]


def test_data_entity_relationships_become_depends_on_edges():
    entity = DataEntity(
        entity_name="Order",
        fields=[FieldInfo(name="customer_id")],
        relationships=[EntityRelationship(from_entity="Order", to_entity="Customer", kind="foreign_key")],
    )
    nodes, edges = build_data_entity_nodes_and_edges([entity], confidence_threshold=0.6)
    assert nodes[0].key_value == "Order"
    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.DEPENDS_ON
    assert edges[0].source_key == "Order"
    assert edges[0].target_key == "Customer"


def test_component_diagram_produces_nodes_and_depends_on_edges():
    diagram = ComponentDiagram(
        components=[Component(name="api", module_paths=["api/a.py"]), Component(name="services", module_paths=["services/b.py"])],
        edges=[DependsOnEdge(source_component="api", target_component="services", call_count=2)],
        architecture_style="layered",
    )
    nodes, edges = build_component_nodes_and_edges(diagram)
    assert {n.key_value for n in nodes} == {"api", "services"}
    assert edges[0].edge_type == EdgeType.DEPENDS_ON
    assert edges[0].source_key == "api"
    assert edges[0].target_key == "services"


def test_capability_owns_entity_when_evidence_file_is_a_member_module():
    cluster = CapabilityCluster(capability_name="Orders", member_modules=["orders/models.py"])
    entity = DataEntity(entity_name="Order", evidence=[Evidence(file="orders/models.py", line=1)])
    contract = APIContract(route="/orders", method="GET", evidence=[Evidence(file="orders/api.py", line=1)])

    edges = build_capability_ownership_edges([cluster], [entity], [contract])

    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.OWNS
    assert edges[0].target_key == "Order"


def test_component_implements_capability_when_modules_overlap():
    diagram = ComponentDiagram(components=[Component(name="orders", module_paths=["orders/models.py"])])
    cluster = CapabilityCluster(capability_name="Order Management", member_modules=["orders/models.py"])

    edges = build_component_implements_capability_edges(diagram, [cluster])

    assert len(edges) == 1
    assert edges[0].edge_type == EdgeType.IMPLEMENTS
    assert edges[0].source_key == "orders"
    assert edges[0].target_key == "Order Management"


def test_conflict_edges_only_built_from_resolve_conflict_resolutions():
    rule = BusinessRule(rule_id="cfg::late_fee_rate", description="", literal_value="0.05", source_kind="config_value")
    entity = DataEntity(entity_name="Plan")
    candidate = ConflictCandidate(
        business_rule=rule, data_entity=entity, field_name="late_fee_rate", rule_value="0.05", entity_value="0.045",
        shared_concept_words=["rate"],
    )
    resolved = ReviewResolution(
        item_id="conflict::1", action=ReviewAction.RESOLVE_CONFLICT, resolved_value=candidate,
        reviewer="auto-resolve-policy", resolution_note="left unresolved -- no side preferred",
    )
    unrelated = ReviewResolution(item_id="low::1", action=ReviewAction.ACCEPT, resolved_value=object())

    edges = build_conflict_edges([resolved, unrelated])

    assert len(edges) == 1
    edge = edges[0]
    assert edge.edge_type == EdgeType.CONFLICTS_WITH
    assert edge.source_key == "cfg::late_fee_rate"
    assert edge.target_key == "Plan"
    assert edge.properties["unresolved"] is True

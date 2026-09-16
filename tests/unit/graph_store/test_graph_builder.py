from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_d.data_model_extractor import DataEntity, EntityRelationship, FieldInfo
from atlaz.agents.domain_d.hld_builder import Component, ComponentDiagram, DependsOnEdge
from atlaz.analysis.config_schema_api import ConfigSchemaAPI
from atlaz.graph_store.graph_builder import (
    build_business_rule_nodes,
    build_conflict_edges,
    build_feature_implemented_by_edges,
    build_feature_nodes_and_edges,
    build_service_nodes_and_edges,
    build_table_and_database_nodes_and_edges,
)
from atlaz.graph_store.schema import EdgeType, NodeLabel
from atlaz.orchestration.confidence import Claim
from atlaz.orchestration.conflicts import Conflict
from atlaz.orchestration.dispute_resolution import ResolvedClaim
from atlaz.shared.evidence import Evidence


def test_business_rule_nodes_carry_tier_confidence_and_status():
    rule = BusinessRule(
        rule_id="billing.py::LATE_FEE_RATE",
        description="Late fee percentage.",
        literal_value="0.045",
        source_kind="code_literal",
        evidence=[Evidence(file="billing.py", line=3)],
    )
    nodes = build_business_rule_nodes([rule], confidence_threshold=0.6, resolved_by_claim_id={})
    assert len(nodes) == 1
    node = nodes[0]
    assert node.label == NodeLabel.BUSINESS_RULE
    assert node.key_value == "billing.py::LATE_FEE_RATE"
    assert node.properties["tier"] == "extractable"
    assert node.properties["literal_value"] == "0.045"
    assert node.properties["status"] == "confirmed"  # no resolution recorded -> default status
    assert "billing.py" in node.properties["evidence_json"]


def test_table_relationships_become_depends_on_edges_and_belong_to_database():
    entity = DataEntity(
        entity_name="Order",
        fields=[FieldInfo(name="customer_id")],
        relationships=[EntityRelationship(from_entity="Order", to_entity="Customer", kind="foreign_key")],
        evidence=[Evidence(file="orders/models.py", line=1)],
    )
    config_schema_api = ConfigSchemaAPI(data_entities=[entity])
    diagram = ComponentDiagram(components=[Component(name="orders", module_paths=["orders/models.py"])])

    nodes, edges = build_table_and_database_nodes_and_edges("repo1", config_schema_api, diagram, confidence_threshold=0.6)

    table_node = next(n for n in nodes if n.label == NodeLabel.TABLE)
    assert table_node.key_value == "Order"
    assert any(e.edge_type == EdgeType.BELONGS_TO and e.source_key == "Order" for e in edges)
    assert any(e.edge_type == EdgeType.DEPENDS_ON and e.source_key == "Order" and e.target_key == "Customer" for e in edges)
    assert any(e.edge_type == EdgeType.OWNS and e.source_key == "orders" and e.target_key == "Order" for e in edges)


def test_service_nodes_produce_contains_and_depends_on_edges():
    diagram = ComponentDiagram(
        components=[Component(name="api", module_paths=["api/a.py"]), Component(name="services", module_paths=["services/b.py"])],
        edges=[DependsOnEdge(source_component="api", target_component="services", call_count=2)],
        architecture_style="layered",
    )
    nodes, edges = build_service_nodes_and_edges("repo1", diagram)
    assert {n.key_value for n in nodes} == {"api", "services"}
    assert any(e.edge_type == EdgeType.CONTAINS and e.source_key == "repo1" and e.target_key == "api" for e in edges)
    assert any(e.edge_type == EdgeType.CONTAINS and e.source_key == "api" and e.target_key == "api/a.py" for e in edges)
    depends_edges = [e for e in edges if e.edge_type == EdgeType.DEPENDS_ON]
    assert len(depends_edges) == 1
    assert depends_edges[0].source_key == "api"
    assert depends_edges[0].target_key == "services"


def test_feature_implemented_by_service_when_modules_overlap():
    diagram = ComponentDiagram(components=[Component(name="orders", module_paths=["orders/models.py"])])
    cluster = CapabilityCluster(capability_name="Order Management", member_modules=["orders/models.py"])

    feature_nodes, feature_edges = build_feature_nodes_and_edges([cluster])
    implemented_by_edges = build_feature_implemented_by_edges([cluster], diagram)

    assert feature_nodes[0].key_value == "feature::Order Management"
    assert any(e.edge_type == EdgeType.HAS_FEATURE for e in feature_edges)
    assert len(implemented_by_edges) == 1
    assert implemented_by_edges[0].edge_type == EdgeType.IMPLEMENTED_BY
    assert implemented_by_edges[0].source_key == "feature::Order Management"
    assert implemented_by_edges[0].target_key == "orders"


def test_conflict_edges_only_built_for_value_mismatch():
    rule_claim = Claim(
        claim_id="domain_b.business_rule_extraction::cfg::late_fee_rate",
        domain="domain_b", entity_id="Plan.late_fee_rate", raw_confidence=0.95,
        assertion={"kind": "value", "value": "0.05"},
    )
    table_claim = Claim(
        claim_id="domain_d.data_model_extractor::Plan.late_fee_rate",
        domain="domain_d", entity_id="Plan.late_fee_rate", raw_confidence=1.0,
        assertion={"kind": "value", "value": "0.045"},
    )
    value_conflict = Conflict(entity_id="Plan.late_fee_rate", claim_a=rule_claim, claim_b=table_claim, conflict_type="value_mismatch")

    dead_claim_a = Claim(claim_id="domain_b.capability_clustering::X::mod.py", domain="domain_b", entity_id="mod.py", raw_confidence=0.7)
    dead_claim_b = Claim(claim_id="domain_d.hld_builder::reachability::mod.py", domain="domain_d", entity_id="mod.py", raw_confidence=0.85)
    dead_conflict = Conflict(entity_id="mod.py", claim_a=dead_claim_a, claim_b=dead_claim_b, conflict_type="dead_vs_active")

    resolved_by_claim_id = {
        rule_claim.claim_id: ResolvedClaim(
            claim_id=rule_claim.claim_id, domain="domain_b", entity_id="Plan.late_fee_rate", confidence=0.95,
            evidence_ids=[], derivation_method="llm_inference", scoring_weight_profile="dispute_resolution",
            status="unresolved_written_both",
        )
    }

    edges = build_conflict_edges([value_conflict, dead_conflict], resolved_by_claim_id)

    assert len(edges) == 1
    edge = edges[0]
    assert edge.edge_type == EdgeType.CONFLICTS_WITH
    assert edge.source_label == NodeLabel.BUSINESS_RULE
    assert edge.source_key == "cfg::late_fee_rate"
    assert edge.target_label == NodeLabel.TABLE
    assert edge.target_key == "Plan"
    assert edge.properties["unresolved"] is True

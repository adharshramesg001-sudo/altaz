from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_d.data_model_extractor import DataEntity, FieldInfo
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.hitl.merge import collect_flagged_items
from atlaz.hitl.models import ReviewItemKind


def _base_kwargs(**overrides):
    kwargs = {
        "gap_finding": GapFinding(),
        "capability_clusters": [],
        "business_rules": [],
        "glossary_terms": [],
        "functional_requirements": [],
        "component_diagram": ComponentDiagram(confidence=0.9),
        "data_entities": [],
        "api_contracts": [],
        "security_controls": [],
        "confidence_threshold": 0.6,
    }
    kwargs.update(overrides)
    return kwargs


def test_gap_finding_is_always_flagged():
    items = collect_flagged_items(**_base_kwargs())
    gap_items = [i for i in items if i.kind == ReviewItemKind.GAP_CONFIRMATION]
    assert len(gap_items) == 1


def test_low_confidence_capability_cluster_is_flagged():
    cluster = CapabilityCluster(capability_name="Orders", confidence=0.3)
    items = collect_flagged_items(**_base_kwargs(capability_clusters=[cluster]))
    low_conf = [i for i in items if i.kind == ReviewItemKind.LOW_CONFIDENCE_FINDING]
    assert len(low_conf) == 1
    assert low_conf[0].subject is cluster


def test_high_confidence_cluster_is_not_flagged():
    cluster = CapabilityCluster(capability_name="Orders", confidence=0.95)
    items = collect_flagged_items(**_base_kwargs(capability_clusters=[cluster]))
    assert not any(i.kind == ReviewItemKind.LOW_CONFIDENCE_FINDING for i in items)


def test_conflicting_rule_and_entity_produce_a_conflict_item():
    rule = BusinessRule(rule_id="cfg::late_fee_rate", description="", literal_value="0.05", source_kind="config_value")
    entity = DataEntity(entity_name="Plan", fields=[FieldInfo(name="late_fee_rate", default_value="0.045")])
    items = collect_flagged_items(**_base_kwargs(business_rules=[rule], data_entities=[entity]))
    conflict_items = [i for i in items if i.kind == ReviewItemKind.CONFLICT]
    assert len(conflict_items) == 1

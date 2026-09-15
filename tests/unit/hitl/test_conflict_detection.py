from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_d.data_model_extractor import DataEntity, FieldInfo
from atlaz.hitl.conflict_detection import find_conflicts


def test_detects_conflicting_rate_between_rule_and_entity_field():
    rule = BusinessRule(
        rule_id="config.yaml::late_fee_rate",
        description="Late fee percentage",
        literal_value="0.05",
        source_kind="config_value",
    )
    entity = DataEntity(entity_name="BillingPlan", fields=[FieldInfo(name="late_fee_rate", default_value="0.045")])

    conflicts = find_conflicts([rule], [entity])

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.rule_value == "0.05"
    assert conflict.entity_value == "0.045"
    assert "rate" in conflict.shared_concept_words


def test_matching_values_are_not_a_conflict():
    rule = BusinessRule(
        rule_id="config.yaml::late_fee_rate", description="", literal_value="0.045", source_kind="config_value"
    )
    entity = DataEntity(entity_name="BillingPlan", fields=[FieldInfo(name="late_fee_rate", default_value="0.045")])

    assert find_conflicts([rule], [entity]) == []


def test_unrelated_identifiers_do_not_conflict():
    rule = BusinessRule(
        rule_id="config.yaml::max_retry_count", description="", literal_value="3", source_kind="config_value"
    )
    entity = DataEntity(entity_name="BillingPlan", fields=[FieldInfo(name="late_fee_rate", default_value="0.045")])

    assert find_conflicts([rule], [entity]) == []

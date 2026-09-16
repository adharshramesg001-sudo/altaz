from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_d.data_model_extractor import DataEntity, FieldInfo
from atlaz.orchestration.confidence import Claim
from atlaz.orchestration.conflicts import detect_conflicts


def test_dead_vs_active_conflict_detected_across_domains():
    claims = [
        Claim(
            claim_id="domain_b.capability_clustering::Loans::loans/svc.py", domain="domain_b", entity_id="loans/svc.py",
            raw_confidence=0.8, assertion={"kind": "capability_membership", "active": True, "capability_name": "Loans"},
        ),
        Claim(
            claim_id="domain_d.hld_builder::reachability::loans/svc.py", domain="domain_d", entity_id="loans/svc.py",
            raw_confidence=0.85, assertion={"kind": "reachability", "reachable": False},
        ),
    ]
    conflicts = detect_conflicts(claims)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "dead_vs_active"
    assert conflicts[0].entity_id == "loans/svc.py"


def test_no_conflict_when_module_is_reachable():
    claims = [
        Claim(
            claim_id="domain_b.capability_clustering::Loans::loans/svc.py", domain="domain_b", entity_id="loans/svc.py",
            raw_confidence=0.8, assertion={"kind": "capability_membership", "active": True, "capability_name": "Loans"},
        ),
        Claim(
            claim_id="domain_d.hld_builder::reachability::loans/svc.py", domain="domain_d", entity_id="loans/svc.py",
            raw_confidence=0.85, assertion={"kind": "reachability", "reachable": True},
        ),
    ]
    assert detect_conflicts(claims) == []


def test_purpose_mismatch_detected_when_no_vocabulary_overlap():
    claims = [
        Claim(
            claim_id="domain_b.capability_clustering::purpose::Billing::svc.py", domain="domain_b", entity_id="svc.py",
            raw_confidence=0.8, assertion={"kind": "purpose", "purpose_text": "Billing"},
        ),
        Claim(
            claim_id="domain_c.frd_extraction::svc.authenticate", domain="domain_c", entity_id="svc.py",
            raw_confidence=0.7, assertion={"kind": "purpose", "purpose_text": "authenticates a user session"},
        ),
    ]
    conflicts = detect_conflicts(claims)
    assert any(c.conflict_type == "purpose_mismatch" for c in conflicts)


def test_purpose_agreement_produces_no_conflict():
    claims = [
        Claim(
            claim_id="domain_b.capability_clustering::purpose::Billing::svc.py", domain="domain_b", entity_id="svc.py",
            raw_confidence=0.8, assertion={"kind": "purpose", "purpose_text": "billing invoice generation"},
        ),
        Claim(
            claim_id="domain_c.frd_extraction::svc.generate_invoice", domain="domain_c", entity_id="svc.py",
            raw_confidence=0.7, assertion={"kind": "purpose", "purpose_text": "generates a billing invoice"},
        ),
    ]
    assert detect_conflicts(claims) == []


def test_same_domain_claims_never_conflict():
    claims = [
        Claim(claim_id="1", domain="domain_b", entity_id="x", raw_confidence=0.8, assertion={"kind": "capability_membership", "active": True}),
        Claim(claim_id="2", domain="domain_b", entity_id="x", raw_confidence=0.8, assertion={"kind": "reachability", "reachable": False}),
    ]
    assert detect_conflicts(claims) == []


def test_value_mismatch_conflict_from_business_rule_vs_data_entity():
    rule = BusinessRule(rule_id="cfg::late_fee_rate", description="", literal_value="0.05", source_kind="config_value")
    entity = DataEntity(entity_name="Plan", fields=[FieldInfo(name="late_fee_rate", default_value="0.045")])

    conflicts = detect_conflicts([], business_rules=[rule], data_entities=[entity])

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "value_mismatch"
    assert conflicts[0].entity_id == "Plan.late_fee_rate"
    assert conflicts[0].claim_a.domain == "domain_b"
    assert conflicts[0].claim_b.domain == "domain_d"

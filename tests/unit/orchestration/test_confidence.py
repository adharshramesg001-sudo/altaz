from atlaz.orchestration.confidence import Claim, score_claim


def test_domain_a_signal_density_is_capped_at_point_six():
    claim = Claim(claim_id="a::1", domain="domain_a", entity_id="x", raw_confidence=0.0, signal_count=50, distinct_source_kinds=5)
    record = score_claim(claim)
    assert record.confidence <= 0.6
    assert record.scoring_weight_profile == "signal_density"
    assert record.derivation_method == "llm_inference"


def test_domain_b_structural_plus_textual_blends_cohesion_and_raw_confidence():
    claim = Claim(claim_id="b::1", domain="domain_b", entity_id="x", raw_confidence=0.8, structural_signal=0.4)
    record = score_claim(claim)
    assert record.confidence == 0.6  # 0.4*0.5 + 0.8*0.5
    assert record.scoring_weight_profile == "structural_plus_textual"


def test_domain_b_without_structural_signal_falls_back_to_raw_confidence():
    claim = Claim(claim_id="b::2", domain="domain_b", entity_id="x", raw_confidence=0.7)
    record = score_claim(claim)
    assert record.confidence == 0.7


def test_domain_c_has_a_point_seven_floor():
    claim = Claim(claim_id="c::1", domain="domain_c", entity_id="x", raw_confidence=0.2)
    record = score_claim(claim)
    assert record.confidence == 0.7
    assert record.derivation_method == "ast_deterministic"


def test_domain_c_above_floor_uses_raw_confidence():
    claim = Claim(claim_id="c::2", domain="domain_c", entity_id="x", raw_confidence=0.95)
    record = score_claim(claim)
    assert record.confidence == 0.95


def test_domain_d_has_a_point_eight_five_floor():
    claim = Claim(claim_id="d::1", domain="domain_d", entity_id="x", raw_confidence=0.5)
    record = score_claim(claim)
    assert record.confidence == 0.85
    assert record.derivation_method == "ast_deterministic"


def test_corroboration_boosts_confidence_but_caps_at_one():
    claim = Claim(
        claim_id="d::2", domain="domain_d", entity_id="x", raw_confidence=0.95,
        corroborating_domains=frozenset({"domain_b", "domain_d"}),
    )
    record = score_claim(claim)
    assert record.confidence == 1.0  # 0.95 * 1.1 = 1.045, capped at 1.0
    assert record.derivation_method == "cross_domain_consolidated"


def test_single_domain_claim_gets_no_multiplier():
    claim = Claim(claim_id="d::3", domain="domain_d", entity_id="x", raw_confidence=0.9, corroborating_domains=frozenset({"domain_d"}))
    record = score_claim(claim)
    assert record.confidence == 0.9


def test_evidence_ids_pass_through_unchanged():
    claim = Claim(claim_id="d::4", domain="domain_d", entity_id="x", raw_confidence=0.9, evidence_ids=["a.py:1", "b.py:2"])
    record = score_claim(claim)
    assert record.evidence_ids == ["a.py:1", "b.py:2"]

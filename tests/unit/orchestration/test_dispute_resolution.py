from atlaz.orchestration.confidence import Claim, ConfidenceRecord
from atlaz.orchestration.conflicts import Conflict
from atlaz.orchestration.dispute_resolution import accept_resolved, auto_resolve_dispute


def _claim(claim_id: str, domain: str, confidence: float) -> Claim:
    return Claim(claim_id=claim_id, domain=domain, entity_id="x", raw_confidence=confidence)


def test_large_confidence_gap_picks_the_higher_side():
    conflict = Conflict(entity_id="x", claim_a=_claim("a", "domain_b", 0.9), claim_b=_claim("b", "domain_d", 0.4), conflict_type="dead_vs_active")
    resolved = auto_resolve_dispute(conflict, {"a": 0.9, "b": 0.4})

    assert len(resolved) == 2
    assert all(r.status == "disputed_resolved" for r in resolved)


def test_close_confidence_leaves_both_unresolved():
    conflict = Conflict(entity_id="x", claim_a=_claim("a", "domain_b", 0.8), claim_b=_claim("b", "domain_d", 0.75), conflict_type="dead_vs_active")
    resolved = auto_resolve_dispute(conflict, {"a": 0.8, "b": 0.75})

    assert len(resolved) == 2
    assert all(r.status == "unresolved_written_both" for r in resolved)
    ids = {r.claim_id for r in resolved}
    assert ids == {"a", "b"}  # neither side dropped -- both written, per Design Principle #6


def test_margin_boundary_is_exactly_point_one_five():
    conflict = Conflict(entity_id="x", claim_a=_claim("a", "domain_b", 0.65), claim_b=_claim("b", "domain_d", 0.5), conflict_type="dead_vs_active")
    resolved = auto_resolve_dispute(conflict, {"a": 0.65, "b": 0.5})
    assert all(r.status == "disputed_resolved" for r in resolved)  # diff == 0.15 -> still resolved (>=)


def test_accept_resolved_marks_ast_grounded_claims_confirmed_and_others_inferred():
    records = [
        ConfidenceRecord(claim_id="c1", domain="domain_d", confidence=0.9, evidence_ids=[], derivation_method="ast_deterministic", scoring_weight_profile="deterministic_adjacent"),
        ConfidenceRecord(claim_id="c2", domain="domain_b", confidence=0.6, evidence_ids=[], derivation_method="llm_inference", scoring_weight_profile="structural_plus_textual"),
    ]
    resolved = accept_resolved(records, disputed_claim_ids=set(), disputed_resolutions=[])

    by_id = {r.claim_id: r for r in resolved}
    assert by_id["c1"].status == "confirmed"
    assert by_id["c2"].status == "inferred"


def test_accept_resolved_does_not_duplicate_already_disputed_claims():
    records = [ConfidenceRecord(claim_id="c1", domain="domain_b", confidence=0.6, evidence_ids=[], derivation_method="llm_inference", scoring_weight_profile="x")]
    from atlaz.orchestration.dispute_resolution import ResolvedClaim

    disputed = [ResolvedClaim(claim_id="c1", domain="domain_b", entity_id="x", confidence=0.6, evidence_ids=[], derivation_method="cross_domain_consolidated", scoring_weight_profile="dispute_resolution", status="disputed_resolved")]

    resolved = accept_resolved(records, disputed_claim_ids={"c1"}, disputed_resolutions=disputed)

    assert len(resolved) == 1
    assert resolved[0].status == "disputed_resolved"

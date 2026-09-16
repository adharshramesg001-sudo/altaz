"""Domain-aware confidence scoring (LLD Section 6.3, node N13
`score_confidence`).

Direct answer to the review finding that a single scoring node handling
heterogeneous evidence types without domain-aware weighting is a modeling
smell: each domain gets its own weight profile, because "confidence" means
structurally different things per domain (signal density for text-mined
Domain A, structural+textual for Domain B, near-deterministic AST grounding
for Domain C, parseable-schema grounding for Domain D).

`Claim` is the one shape every domain output gets normalized into before
scoring (`atlaz.orchestration.nodes.make_score_confidence_node` builds these
from each `DomainXOutput`); this module never imports domain agent
dataclasses directly, so it stays reusable if/when Domain E claims exist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_DOMAIN_A_CAP = 0.6  # Domain A: never high-confidence -- always advisory (LLD Section 6.3 table)
_DOMAIN_C_FLOOR = 0.7  # Domain C: high floor -- function signatures are near-deterministic
_DOMAIN_D_FLOOR = 0.85  # Domain D: highest-confidence domain -- closest to ground truth

_AST_GROUNDED_DOMAINS = {"domain_c", "domain_d"}


@dataclass(slots=True)
class Claim:
    """One scoreable assertion, normalized out of a domain's own dataclass
    output. `entity_id` is the code entity the claim is about (used by both
    this module's corroboration multiplier and `orchestration.conflicts`'
    cross-domain matching) -- empty string when a claim has no single code
    entity to anchor to (e.g. Domain A's gap, or a Domain B glossary term)."""

    claim_id: str
    domain: str  # "domain_a".."domain_e"
    entity_id: str
    raw_confidence: float  # the agent's own already-computed confidence
    evidence_ids: list[str] = field(default_factory=list)
    structural_signal: float | None = None  # e.g. CapabilityCluster.cohesion_score
    signal_count: int = 0  # Domain A only: number of candidate signals
    distinct_source_kinds: int = 0  # Domain A only
    corroborating_domains: frozenset[str] = frozenset()
    # Structured payload `orchestration.conflicts` inspects to classify
    # cross-domain contradictions (e.g. {"kind": "reachability", "reachable": False}).
    # Never read by the scoring functions in this module -- scoring and
    # conflict classification are deliberately independent passes over the
    # same `Claim`.
    assertion: dict = field(default_factory=dict)


@dataclass(slots=True)
class ConfidenceRecord:
    claim_id: str
    domain: str
    confidence: float
    evidence_ids: list[str]
    derivation_method: str  # "ast_deterministic" | "llm_inference" | "cross_domain_consolidated"
    scoring_weight_profile: str


def score_claim(claim: Claim) -> ConfidenceRecord:
    weight_profile, weighted = _apply_weight_profile(claim)
    multiplier = _source_agreement_multiplier(claim)
    final_confidence = round(min(1.0, weighted * multiplier), 3)
    return ConfidenceRecord(
        claim_id=claim.claim_id,
        domain=claim.domain,
        confidence=final_confidence,
        evidence_ids=claim.evidence_ids,
        derivation_method=_derivation_method(claim),
        scoring_weight_profile=weight_profile,
    )


def _apply_weight_profile(claim: Claim) -> tuple[str, float]:
    if claim.domain == "domain_a":
        return "signal_density", _signal_density(claim)
    if claim.domain == "domain_b":
        return "structural_plus_textual", _structural_plus_textual(claim)
    if claim.domain == "domain_c":
        return "ast_grounded", max(_DOMAIN_C_FLOOR, claim.raw_confidence)
    if claim.domain == "domain_d":
        return "deterministic_adjacent", max(_DOMAIN_D_FLOOR, claim.raw_confidence)
    return "not_applicable", 0.0  # domain_e: never executed, kept for completeness


def _signal_density(claim: Claim) -> float:
    """Weighted by signal count and source diversity, capped at 0.6 --
    Domain A's textual signals are never allowed to read as high-confidence
    regardless of how many independent hints accumulate."""
    density = min(1.0, claim.signal_count / 5)
    diversity = min(1.0, claim.distinct_source_kinds / 3)
    return round(_DOMAIN_A_CAP * (0.7 * density + 0.3 * diversity), 3)


def _structural_plus_textual(claim: Claim) -> float:
    """call-graph cohesion score x 0.5 + literal-match specificity x 0.5
    (LLD Section 6.3). `structural_signal` carries the cohesion score when
    the claim has one (CapabilityCluster); `raw_confidence` stands in for
    "literal-match specificity" -- it is already computed deterministically
    from evidence breadth/specificity by every Domain B agent."""
    if claim.structural_signal is None:
        return claim.raw_confidence
    return round(claim.structural_signal * 0.5 + claim.raw_confidence * 0.5, 3)


def _source_agreement_multiplier(claim: Claim) -> float:
    """1.0 if only one domain made the claim; boosted up to 1.2 (capped at
    1.0 final by the caller) if multiple domains independently corroborate
    it -- the same corroboration-boosting principle as Cortex's Noisy-OR
    fusion, applied at the claim level."""
    corroborators = len(claim.corroborating_domains)
    if corroborators <= 1:
        return 1.0
    return round(min(1.2, 1.0 + 0.1 * (corroborators - 1)), 3)


def _derivation_method(claim: Claim) -> str:
    if len(claim.corroborating_domains) > 1:
        return "cross_domain_consolidated"
    if claim.domain in _AST_GROUNDED_DOMAINS:
        return "ast_deterministic"
    return "llm_inference"

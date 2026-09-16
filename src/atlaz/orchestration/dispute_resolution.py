"""Auto-resolve dispute policy engine (LLD Section 8.6-8.7, nodes N16
`auto_resolve_dispute` / N15 `accept_resolved`).

This is the no-HITL dispute-resolution variant the LLD documents: a
confidence-diff threshold decides whether one side of a cross-domain
conflict is accepted, or -- per Design Principle #6 ("absence is a valid,
non-fabricated answer") -- both sides are written, unresolved, as competing
hypotheses. This is distinct from `atlaz.hitl.auto_resolve`, which
continues to handle the separate gap-confirmation/low-confidence-finding
review-item flow (three origins, LLD's prior design); this module handles
only the N11X cross-domain `Conflict` shape.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlaz.orchestration.confidence import Claim, ConfidenceRecord
from atlaz.orchestration.conflicts import Conflict

DISPUTE_CONFIDENCE_MARGIN = 0.15


@dataclass(slots=True)
class ResolvedClaim:
    claim_id: str
    domain: str
    entity_id: str
    confidence: float
    evidence_ids: list[str]
    derivation_method: str
    scoring_weight_profile: str
    status: str  # "confirmed" | "inferred" | "disputed_resolved" | "unresolved_written_both"


def auto_resolve_dispute(conflict: Conflict, confidence_by_claim_id: dict[str, float]) -> list[ResolvedClaim]:
    """§8.6's `auto_resolve()`, translated to this codebase's `Conflict`/
    `ConfidenceRecord` shapes. Returns one `ResolvedClaim` per side of the
    conflict (both statuses agree: `disputed_resolved` for both the winner
    and the loser when a pick is made, `unresolved_written_both` for both
    when it isn't) -- the loser is still written, just labeled, matching
    the LLD's "no side is silently overwritten" contract.
    """
    a, b = conflict.claim_a, conflict.claim_b
    conf_a = confidence_by_claim_id.get(a.claim_id, a.raw_confidence)
    conf_b = confidence_by_claim_id.get(b.claim_id, b.raw_confidence)

    if abs(conf_a - conf_b) >= DISPUTE_CONFIDENCE_MARGIN:
        return [
            _resolved(a, conf_a, "disputed_resolved"),
            _resolved(b, conf_b, "disputed_resolved"),
        ]
    return [
        _resolved(a, conf_a, "unresolved_written_both"),
        _resolved(b, conf_b, "unresolved_written_both"),
    ]


def accept_resolved(
    confidence_records: list[ConfidenceRecord],
    disputed_claim_ids: set[str],
    disputed_resolutions: list[ResolvedClaim],
) -> list[ResolvedClaim]:
    """N15: writes the final status onto every claim, disputed or not.
    Non-disputed claims are `confirmed` when AST/deterministic-grounded
    (Domain C/D) or `inferred` when LLM-assisted (Domain A/B) --
    `record.derivation_method` already distinguishes the two."""
    resolved: list[ResolvedClaim] = list(disputed_resolutions)
    for record in confidence_records:
        if record.claim_id in disputed_claim_ids:
            continue  # already covered by disputed_resolutions
        status = "confirmed" if record.derivation_method == "ast_deterministic" else "inferred"
        resolved.append(
            ResolvedClaim(
                claim_id=record.claim_id,
                domain=record.domain,
                entity_id="",
                confidence=record.confidence,
                evidence_ids=record.evidence_ids,
                derivation_method=record.derivation_method,
                scoring_weight_profile=record.scoring_weight_profile,
                status=status,
            )
        )
    return resolved


def _resolved(claim: Claim, confidence: float, status: str) -> ResolvedClaim:
    derivation_method = "cross_domain_consolidated" if status == "disputed_resolved" else "llm_inference"
    return ResolvedClaim(
        claim_id=claim.claim_id,
        domain=claim.domain,
        entity_id=claim.entity_id,
        confidence=confidence,
        evidence_ids=claim.evidence_ids,
        derivation_method=derivation_method,
        scoring_weight_profile="dispute_resolution",
        status=status,
    )

"""Cross-domain conflict detection (LLD Section 8.2, node N11X
`detect_cross_domain_conflicts`).

Direct fix for the review gap "where does a contradiction between two
domains get caught? Right now nothing catches cross-domain contradictions."
Indexes claims by the code entity they reference and flags mutually
exclusive assertions across domains -- e.g. Domain B's capability
clustering claims module `X` implements "loan approval" while Domain D's
`hld_builder` (via call-graph reachability) marks the same module
unreachable: exactly a `dead_vs_active` conflict, caught here rather than
silently absorbed into a single confidence number.

Two conflict types are detected structurally from `Claim.assertion` (built
by `orchestration.nodes` alongside each `Claim`, see
`make_detect_cross_domain_conflicts_node`):
- `dead_vs_active`: a Domain B "this module is an active capability" claim
  against a Domain D "this module is unreachable" claim for the same
  entity.
- `purpose_mismatch`: a Domain C behavior claim and a Domain B capability
  claim about the same module whose descriptive text shares no vocabulary
  -- weak signal by nature (text overlap, not semantic understanding), but
  real and evidence-backed rather than an LLM guess.

A third type, `value_mismatch`, is the LLD-predating "a BusinessRule
literal_value doesn't match a corresponding DataEntity field default"
check already implemented in `atlaz.hitl.conflict_detection` -- kept as-is
and folded in here as a third, legitimate conflict kind (not a duplicate of
the two above, which are about *what a module is for*, not *what value it
uses*).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations

from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.hitl.conflict_detection import ConflictCandidate, find_conflicts
from atlaz.orchestration.confidence import Claim

_STOPWORDS = frozenset({"the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with", "is", "are"})


@dataclass(slots=True)
class Conflict:
    entity_id: str
    claim_a: Claim
    claim_b: Claim
    conflict_type: str  # "purpose_mismatch" | "dead_vs_active" | "value_mismatch"


def detect_conflicts(
    claims: list[Claim],
    business_rules: list[BusinessRule] | None = None,
    data_entities: list[DataEntity] | None = None,
) -> list[Conflict]:
    conflicts = list(_detect_entity_conflicts(claims))
    conflicts.extend(_detect_value_conflicts(business_rules or [], data_entities or []))
    return conflicts


def _detect_entity_conflicts(claims: list[Claim]) -> list[Conflict]:
    claims_by_entity: dict[str, list[Claim]] = defaultdict(list)
    for claim in claims:
        if claim.entity_id:
            claims_by_entity[claim.entity_id].append(claim)

    conflicts: list[Conflict] = []
    for entity_id, group in claims_by_entity.items():
        if len(group) < 2:
            continue
        for a, b in combinations(group, 2):
            if a.domain == b.domain:
                continue
            conflict_type = _classify(a, b)
            if conflict_type is not None:
                conflicts.append(Conflict(entity_id=entity_id, claim_a=a, claim_b=b, conflict_type=conflict_type))
    return conflicts


def _classify(a: Claim, b: Claim) -> str | None:
    kind_a = a.assertion.get("kind") if a.assertion else None
    kind_b = b.assertion.get("kind") if b.assertion else None

    active, reachability = None, None
    for claim, kind in ((a, kind_a), (b, kind_b)):
        if kind == "capability_membership" and claim.assertion.get("active"):
            active = claim
        if kind == "reachability":
            reachability = claim
    if active is not None and reachability is not None and reachability.assertion.get("reachable") is False:
        return "dead_vs_active"

    purpose_claims = [c for c, k in ((a, kind_a), (b, kind_b)) if k == "purpose"]
    if len(purpose_claims) == 2:
        text_a = _tokenize(purpose_claims[0].assertion.get("purpose_text", ""))
        text_b = _tokenize(purpose_claims[1].assertion.get("purpose_text", ""))
        if text_a and text_b and not (text_a & text_b):
            return "purpose_mismatch"

    return None


def _tokenize(text: str) -> set[str]:
    return {w for w in text.lower().split() if w not in _STOPWORDS and len(w) > 2}


def _detect_value_conflicts(business_rules: list[BusinessRule], data_entities: list[DataEntity]) -> list[Conflict]:
    conflicts: list[Conflict] = []
    for candidate in find_conflicts(business_rules, data_entities):
        entity_id = f"{candidate.data_entity.entity_name}.{candidate.field_name}"
        conflicts.append(
            Conflict(
                entity_id=entity_id,
                claim_a=_claim_from_business_rule(candidate),
                claim_b=_claim_from_data_entity(candidate),
                conflict_type="value_mismatch",
            )
        )
    return conflicts


def _claim_from_business_rule(candidate: ConflictCandidate) -> Claim:
    rule = candidate.business_rule
    return Claim(
        claim_id=f"domain_b.business_rule_extraction::{rule.rule_id}",
        domain="domain_b",
        entity_id=f"{candidate.data_entity.entity_name}.{candidate.field_name}",
        raw_confidence=rule.confidence,
        evidence_ids=[f"{e.file}:{e.line}" for e in rule.evidence if e.file],
        assertion={"kind": "value", "value": candidate.rule_value},
    )


def _claim_from_data_entity(candidate: ConflictCandidate) -> Claim:
    entity = candidate.data_entity
    return Claim(
        claim_id=f"domain_d.data_model_extractor::{entity.entity_name}.{candidate.field_name}",
        domain="domain_d",
        entity_id=f"{entity.entity_name}.{candidate.field_name}",
        raw_confidence=entity.confidence,
        evidence_ids=[f"{e.file}:{e.line}" for e in entity.evidence if e.file],
        assertion={"kind": "value", "value": candidate.entity_value},
    )

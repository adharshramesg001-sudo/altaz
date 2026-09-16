"""Business Case Gap Detector (LLD Section 7.1, second Domain A node).

The one place in the system where the pipeline is structurally prevented
from reaching its own conclusion: `GapFinding.tier` is a fixed literal,
never computed or assigned by a confidence score. No code path in this
agent can promote it to INFERABLE or EXTRACTABLE, no matter how many
candidate signals `readme_commit_signal_miner` gathered. This node's only
job is to emit the explicit `Gap(category="business_case",
status="external_only")` record (LLD Section 8.2's hard rule, not an LLM
judgment) -- it does not gather signals itself; that is
`readme_commit_signal_miner`'s job (§7.1's first node).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.agents.domain_a.readme_commit_signal_miner import CandidateSignal
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier


@dataclass(frozen=True, slots=True)
class GapFinding:
    corner: str = "business_case_vision"
    category: str = "business_case"
    tier: Tier = Tier.EXTERNAL_ONLY  # forced back to EXTERNAL_ONLY in __post_init__, whatever is passed in
    status: str = "external_only"  # forced in __post_init__ -- permanent, never resolved (LLD §14.2.1 Gap node)
    signal_found: bool = False
    candidate_signals: list[CandidateSignal] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    routed_to: str = "hitl_gate"

    def __post_init__(self) -> None:
        # `tier`/`status` stay normal __init__ arguments (not init=False) so a
        # checkpoint round-trip -- LangGraph's serializer reconstructs this
        # dataclass via GapFinding(**fields), both included -- can rebuild
        # it; __post_init__ is what actually keeps them fixed, since
        # frozen=True alone doesn't stop a value from being *passed in* at
        # construction.
        object.__setattr__(self, "tier", Tier.EXTERNAL_ONLY)
        object.__setattr__(self, "status", "external_only")


class BusinessCaseGapDetector:
    def run(self, signals: list[CandidateSignal]) -> GapFinding:
        return GapFinding(
            signal_found=len(signals) > 0,
            candidate_signals=signals,
            evidence=[s.evidence for s in signals] or [Evidence.gap()],
        )

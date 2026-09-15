"""Business Case Gap Detector (LLD Section 5, Corner #1).

The one place in the system where the pipeline is structurally prevented
from reaching its own conclusion: `GapFinding.tier` is a fixed literal,
never computed or assigned by a confidence score. No code path in this
agent can promote it to INFERABLE or EXTRACTABLE, no matter how many
candidate signals are gathered. Every `CandidateSignal` is raw evidence for
a human -- the raw hint itself, never an LLM-synthesized conclusion about
*why* the product exists.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.shared.identifiers import identifier_matches_any
from atlaz.ingestion.models import RepoInventory
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

RATIONALE_PATTERNS = re.compile(
    r"\b(because|this exists to|workaround for|the reason|in order to|so that)\b", re.IGNORECASE
)
BILLING_IDENTIFIER_WORDS = frozenset(
    {"plan", "tier", "subscription", "billing", "entitlement", "feature", "flag", "gate", "pricing"}
)
_FOUNDING_COMMIT_WINDOW = 20


@dataclass(slots=True)
class CandidateSignal:
    source_kind: str  # "readme" | "commit_message" | "comment" | "naming_pattern" | "billing_structure"
    text: str
    evidence: Evidence


@dataclass(frozen=True, slots=True)
class GapFinding:
    corner: str = "business_case_vision"
    tier: Tier = Tier.EXTERNAL_ONLY  # forced back to EXTERNAL_ONLY in __post_init__, whatever is passed in
    signal_found: bool = False
    candidate_signals: list[CandidateSignal] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    routed_to: str = "hitl_gate"

    def __post_init__(self) -> None:
        # `tier` stays a normal __init__ argument (not init=False) so a
        # checkpoint round-trip -- LangGraph's serializer reconstructs this
        # dataclass via GapFinding(**fields), tier included -- can rebuild
        # it; __post_init__ is what actually keeps it fixed, since frozen=True
        # alone doesn't stop a value from being *passed in* at construction.
        object.__setattr__(self, "tier", Tier.EXTERNAL_ONLY)


class BusinessCaseGapDetector:
    def run(
        self,
        inventory: RepoInventory,
        parsed: list[ParsedModule],
        glossary: list[GlossaryTerm] | None = None,
    ) -> GapFinding:
        signals: list[CandidateSignal] = []
        signals.extend(self._scan_readmes(inventory))
        signals.extend(self._scan_comments(parsed))
        signals.extend(self._scan_naming_and_glossary(glossary or []))
        signals.extend(self._scan_billing_structure(parsed))

        finding = GapFinding(
            signal_found=len(signals) > 0,
            candidate_signals=signals,
            evidence=[s.evidence for s in signals] or [Evidence.gap()],
        )
        return finding

    def _scan_readmes(self, inventory: RepoInventory) -> list[CandidateSignal]:
        signals = []
        for readme_path in inventory.readme_paths:
            try:
                with open(inventory.abs_path(readme_path), encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue
            for match in RATIONALE_PATTERNS.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                snippet = content[max(0, match.start() - 40) : match.end() + 80].strip()
                signals.append(
                    CandidateSignal(
                        source_kind="readme",
                        text=snippet,
                        evidence=Evidence(file=readme_path, line=line),
                    )
                )
            if content.strip() and not signals:
                # The README exists and has content but no explicit rationale
                # language -- still worth one weak signal citing its opening
                # line, rather than silently discarding the file entirely.
                first_line = content.strip().splitlines()[0]
                signals.append(
                    CandidateSignal(
                        source_kind="readme",
                        text=first_line,
                        evidence=Evidence(file=readme_path, line=1),
                    )
                )
        return signals

    def _scan_comments(self, parsed: list[ParsedModule]) -> list[CandidateSignal]:
        signals = []
        for module in parsed:
            for comment in module.comments:
                if RATIONALE_PATTERNS.search(comment.text):
                    signals.append(
                        CandidateSignal(
                            source_kind="comment",
                            text=comment.text,
                            evidence=Evidence(file=module.file_path, line=comment.line),
                        )
                    )
        return signals

    def _scan_naming_and_glossary(self, glossary: list[GlossaryTerm]) -> list[CandidateSignal]:
        signals = []
        top_terms = sorted(glossary, key=lambda t: t.occurrence_count, reverse=True)[:10]
        for term in top_terms:
            evidence = term.evidence[0] if term.evidence else Evidence.gap()
            signals.append(
                CandidateSignal(
                    source_kind="naming_pattern",
                    text=term.term,
                    evidence=evidence,
                )
            )
        return signals

    def _scan_billing_structure(self, parsed: list[ParsedModule]) -> list[CandidateSignal]:
        signals = []
        for module in parsed:
            for cls in module.classes:
                if identifier_matches_any(cls.name, BILLING_IDENTIFIER_WORDS):
                    signals.append(
                        CandidateSignal(
                            source_kind="billing_structure",
                            text=f"class {cls.name}",
                            evidence=Evidence(file=module.file_path, line=cls.line_start),
                        )
                    )
                for f in cls.fields:
                    if identifier_matches_any(f.name, BILLING_IDENTIFIER_WORDS):
                        signals.append(
                            CandidateSignal(
                                source_kind="billing_structure",
                                text=f"{cls.name}.{f.name}" + (f" = {f.value_expr}" if f.value_expr else ""),
                                evidence=Evidence(file=module.file_path, line=f.line or cls.line_start),
                            )
                        )
        return signals

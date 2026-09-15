"""Evidence object shared across every agent (LLD Section 13.2).

Every finding in the system must be traceable back to a file, line, and
commit -- or explicitly marked as a flagged gap. There is no other way for
a fact to enter the knowledge graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.shared.tier import Tier

NO_EVIDENCE_NOTE = "none - flagged gap"


@dataclass(frozen=True, slots=True)
class Evidence:
    file: str | None = None
    line: int | None = None
    commit: str | None = None
    note: str = ""

    @classmethod
    def gap(cls, note: str = NO_EVIDENCE_NOTE) -> Evidence:
        """Construct the evidence record for an external-only / unfilled gap."""
        return cls(file=None, line=None, commit=None, note=note)

    @property
    def is_gap(self) -> bool:
        return self.file is None and self.line is None and self.commit is None

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "line": self.line,
            "commit": self.commit,
            "note": self.note,
        }


@dataclass(slots=True)
class EvidencedFinding:
    """Mixin-style base for any dataclass that needs tier + confidence + evidence.

    Not all agent dataclasses inherit from this directly (some predate this
    module's factoring and simply mirror the same three fields), but every
    agent output MUST carry tier, confidence, and evidence -- this class is
    the canonical shape and the one new agents should build on.
    """

    tier: Tier
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)

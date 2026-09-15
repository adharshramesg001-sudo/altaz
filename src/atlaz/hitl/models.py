"""ReviewItem -- the single shape every flagged-item origin normalizes into
before entering the consolidated HITL gate (LLD Section 10, three origins:
gap confirmation, low-confidence inference, intended-vs-implemented conflict).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ReviewItemKind(str, Enum):
    GAP_CONFIRMATION = "gap_confirmation"
    LOW_CONFIDENCE_FINDING = "low_confidence_finding"
    CONFLICT = "conflict"


class ReviewAction(str, Enum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"
    RESOLVE_CONFLICT = "resolve_conflict"


@dataclass(slots=True)
class ReviewItem:
    item_id: str
    kind: ReviewItemKind
    source_domain: str  # e.g. "domain_a", "domain_b.capability_clustering"
    summary: str  # human-readable one-liner for the review card
    subject: Any  # the underlying finding dataclass (GapFinding, BusinessRule, ConflictCandidate, ...)
    confidence: float | None = None


@dataclass(slots=True)
class ReviewResolution:
    item_id: str
    action: ReviewAction
    resolved_value: Any = None
    reviewer: str = ""
    resolution_note: str = ""

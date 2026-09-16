"""ReviewItem -- the single shape every flagged-item origin normalizes into
before entering the consolidated HITL gate (two origins: gap confirmation,
low-confidence inference). Intended-vs-implemented conflicts are no longer
a third origin here: the new LLD routes every cross-domain contradiction
-- including the rule-vs-implementation `value_mismatch` check this HITL
gate used to surface as `ReviewItemKind.CONFLICT` -- through
`atlaz.orchestration.conflicts`/`dispute_resolution` instead (N11X-N16),
which is authoritative for conflicts now.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ReviewItemKind(str, Enum):
    GAP_CONFIRMATION = "gap_confirmation"
    LOW_CONFIDENCE_FINDING = "low_confidence_finding"


class ReviewAction(str, Enum):
    ACCEPT = "accept"
    EDIT = "edit"
    REJECT = "reject"


@dataclass(slots=True)
class ReviewItem:
    item_id: str
    kind: ReviewItemKind
    source_domain: str  # e.g. "domain_a", "domain_b.capability_clustering"
    summary: str  # human-readable one-liner for the review card
    subject: Any  # the underlying finding dataclass (GapFinding, BusinessRule, ConflictCandidate, ...)
    confidence: float | None = None
    # LOW_CONFIDENCE_FINDING only: the value from `hitl.natural_keys.natural_key(subject)`
    # at flag time, used to re-match this item's subject after a checkpoint round-trip
    # (see `hitl.natural_keys` for why `id()` can't be used for this).
    natural_key: str = ""


@dataclass(slots=True)
class ReviewResolution:
    item_id: str
    action: ReviewAction
    resolved_value: Any = None
    reviewer: str = ""
    resolution_note: str = ""

"""Confidence-tiering model shared by every extraction agent.

Per the AtlaZ HLD, a corner of product knowledge is classified into exactly
one of three tiers *before* extraction touches it, so a guess is never
presented with the same certainty as a fact:

- EXTRACTABLE: code is the primary, near-complete source. Extracted
  deterministically (parsing / static analysis).
- INFERABLE: code + cross-referencing yields a defensible hypothesis.
  Extracted with a confidence score and cited evidence.
- EXTERNAL_ONLY: never lived in code (strategy, market, contracts). The
  system detects the gap and asks a human; it never fabricates.
"""

from __future__ import annotations

from enum import Enum


class Tier(str, Enum):
    EXTRACTABLE = "extractable"
    INFERABLE = "inferable"
    EXTERNAL_ONLY = "external_only"

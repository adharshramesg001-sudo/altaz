"""Plain keyword-overlap relevance scoring, no LLM or embeddings -- shared
by `atlaz.enhancement.impact_analysis` (scores a request against graph
nodes) and `atlaz.migration.unit_builder` (scores a migration unit's name
against business rules/tables/APIs/security controls that carry no direct
ownership edge to it in the current schema).
"""

from __future__ import annotations

import re

_STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with",
    "add", "new", "please", "should", "want", "need", "make", "so", "that",
    "this", "it", "be", "is", "are", "we", "our", "support", "feature",
}


def tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def overlap_score(a: str, b: str) -> int:
    return len(tokenize(a) & tokenize(b))

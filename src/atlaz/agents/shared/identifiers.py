"""Identifier word-splitting shared by every agent that matches vocabulary
against snake_case/camelCase/PascalCase identifiers (Domain Glossary,
Business Case Gap Detector). A plain `\\bword\\b` regex against the raw
identifier does not work: there is no boundary between "n" and "T" in
"PlanTier", and "_" counts as a word character so there is none between
"_" and "t" in "pricing_tier" either. Splitting into word tokens first and
matching against those avoids both failure modes.
"""

from __future__ import annotations

import re

_WORD_BOUNDARY = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def split_identifier_words(identifier: str, *, min_length: int = 1) -> list[str]:
    parts = re.split(r"[_\-\s]+", identifier)
    words: list[str] = []
    for part in parts:
        if not part:
            continue
        sub_words = _WORD_BOUNDARY.findall(part)
        words.extend(w.lower() for w in sub_words if len(w) >= min_length)
    return words


def identifier_matches_any(identifier: str, vocabulary: frozenset[str]) -> bool:
    return any(word in vocabulary for word in split_identifier_words(identifier))

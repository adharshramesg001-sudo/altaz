"""Guards LLM-generated Cypher before it ever reaches the database.

Sections 12.1's ReasoningAgent maps a natural-language question to a Cypher
query via the LLM. An LLM-authored query running against a real database is
untrusted input in exactly the way a hand-typed SQL string from a web form
is: nothing stops a malformed or adversarially-prompted response from
containing a write/delete clause. This is a minimal allowlist -- read-only
clauses only -- not a full Cypher parser, so it errs toward rejecting
anything it isn't confident about rather than trying to sanitize it.
"""

from __future__ import annotations

import re

_WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|CALL|LOAD\s+CSV|FOREACH)\b", re.IGNORECASE
)
_ALLOWED_LEADING_KEYWORDS = re.compile(r"^\s*(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", re.IGNORECASE)


class UnsafeCypherError(ValueError):
    pass


def ensure_read_only(cypher: str) -> str:
    stripped = cypher.strip().strip(";").strip()
    if not stripped:
        raise UnsafeCypherError("empty query")
    if not _ALLOWED_LEADING_KEYWORDS.match(stripped):
        raise UnsafeCypherError(f"query must start with MATCH/WITH/UNWIND/RETURN: {stripped[:80]!r}")
    if _WRITE_KEYWORDS.search(stripped):
        raise UnsafeCypherError(f"query contains a write/procedure-call clause: {stripped[:120]!r}")
    return stripped

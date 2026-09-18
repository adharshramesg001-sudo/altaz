"""Scans a migration unit's own source files for static/technical constants
-- ports, timeouts, versions, sizes, flags -- so generation (which never
sees the original file source, see `generator.py`) doesn't have to invent
plausible-looking values or silently drop real ones.

Deliberately migration-time, not ingestion-time: works on repos already
ingested, no schema change, no re-ingestion required. Mirrors
`agents.domain_b.business_rule_extractor`'s exact mechanism (a deterministic
`identifier = literal` regex scan, no LLM) but *without* that extractor's
`BUSINESS_IDENTIFIER_PATTERN` filter -- this is deliberately the broader,
business-agnostic net: `MAX_RETRIES`, `TIMEOUT_SECONDS`, `REDIS_PORT` are
exactly the kind of technical constant a business-rule scan skips on
purpose, but that a stack migration needs to preserve.

v1 scope: scans source files only (a unit's own files, read from disk).
Config files (.env, settings.yaml) are not parsed here -- `unit_builder.py`
already classifies them separately, and parsing structured config formats
is a documented follow-up, not done this pass.
"""

from __future__ import annotations

import re
from pathlib import Path

from atlaz.migration.models import StaticValue

_ASSIGNMENT_PATTERN = re.compile(
    r"^[ \t]*(?:public\s+|private\s+|protected\s+|static\s+|final\s+|const\s+|let\s+|var\s+|self\.)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[\w\[\]\.<>]+)?\s*=\s*"
    r"(\"[^\"]*\"|'[^']*'|-?\d+(?:\.\d+)?)\s*[,;]?\s*$",
    re.MULTILINE,
)

_PER_FILE_LIMIT = 20
_UNIT_LIMIT = 30


def extract_static_values(repo_path: str, file_paths: list[str]) -> list[StaticValue]:
    values: list[StaticValue] = []
    for file_path in file_paths:
        if len(values) >= _UNIT_LIMIT:
            break
        full_path = Path(repo_path) / file_path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        matches = list(_ASSIGNMENT_PATTERN.finditer(content))[:_PER_FILE_LIMIT]
        for match in matches:
            if len(values) >= _UNIT_LIMIT:
                break
            identifier, literal = match.group(1), match.group(2)
            line = content.count("\n", 0, match.start()) + 1
            values.append(StaticValue(name=identifier, value=literal.strip("\"'"), file_path=file_path, line=line))
    return values

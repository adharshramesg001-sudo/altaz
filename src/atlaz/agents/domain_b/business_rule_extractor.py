"""Business Rule Extraction Agent (LLD Section 6.2, Corner #6 -- fully-extractable half).

Scans source files for numeric/string literal assignments adjacent to
business-suggestive identifier names, plus a direct pass over config files
for the same identifier patterns. The LLM is used only to generate a
one-line human-readable description of what a matched rule appears to do --
`literal_value` and `evidence` are extracted deterministically and are not
LLM output, keeping this corner's core facts at near-1.0 confidence as the
HLD tiering requires.

Scans raw file text (via `RepoInventory`) rather than `ParsedModule` alone:
the language-neutral `ParsedModule` intentionally does not carry function-body
statements, and a business constant is just as likely to be a module-level
or function-local assignment as a class field. This mirrors the same
"direct file read for a narrow, deterministic pattern" precedent the
migration scanner in `DataModelExtractor` already sets.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from atlaz.ingestion.models import RepoInventory
from atlaz.llm.client import BaseLLMClient
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

BUSINESS_IDENTIFIER_PATTERN = re.compile(
    r"(rate|threshold|limit|fee|tier|cutoff|quota|discount|penalty|deadline|max_|min_)",
    re.IGNORECASE,
)

# identifier = <literal> assignment. Deliberately language-agnostic (covers
# Python/JS/TS/Go/Java/C#-shaped code) rather than one AST walk per language,
# since this agent's evidence is the textual assignment itself, not its
# surrounding syntax tree.
_ASSIGNMENT_PATTERN = re.compile(
    r"^[ \t]*(?:public\s+|private\s+|protected\s+|static\s+|final\s+|const\s+|let\s+|var\s+|self\.)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?::\s*[\w\[\]\.<>]+)?\s*=\s*"
    r"(\"[^\"]*\"|'[^']*'|-?\d+(?:\.\d+)?)\s*[,;]?\s*$",
    re.MULTILINE,
)

_DESCRIPTION_SCHEMA = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
    },
    "required": ["description"],
}


@dataclass(slots=True)
class BusinessRule:
    rule_id: str
    description: str
    literal_value: str
    source_kind: str  # "code_literal" | "config_value"
    tier: Tier = Tier.EXTRACTABLE
    confidence: float = 0.95
    evidence: list[Evidence] = field(default_factory=list)


class BusinessRuleExtractor:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(self, inventory: RepoInventory) -> list[BusinessRule]:
        rules: list[BusinessRule] = []
        rules.extend(self._scan_code_literals(inventory))
        rules.extend(self._scan_config_values(inventory))
        for rule in rules:
            rule.description = self._describe(rule)
        return rules

    def _scan_code_literals(self, inventory: RepoInventory) -> list[BusinessRule]:
        rules: list[BusinessRule] = []
        seen: set[tuple[str, str]] = set()
        for file_record in inventory.files:
            if not file_record.language:
                continue
            try:
                content = Path(inventory.abs_path(file_record.path)).read_text(
                    encoding="utf-8", errors="ignore"
                )
            except OSError:
                continue

            for match in _ASSIGNMENT_PATTERN.finditer(content):
                identifier, literal = match.group(1), match.group(2)
                if not BUSINESS_IDENTIFIER_PATTERN.search(identifier):
                    continue
                key = (file_record.path, identifier)
                if key in seen:
                    continue
                seen.add(key)
                line = content.count("\n", 0, match.start()) + 1
                rules.append(
                    BusinessRule(
                        rule_id=f"{file_record.path}::{identifier}",
                        description="",
                        literal_value=literal.strip("\"'"),
                        source_kind="code_literal",
                        evidence=[Evidence(file=file_record.path, line=line)],
                    )
                )
        return rules

    def _scan_config_values(self, inventory: RepoInventory) -> list[BusinessRule]:
        rules: list[BusinessRule] = []
        for config_path in inventory.config_paths:
            data = _load_config_file(inventory.abs_path(config_path))
            if not isinstance(data, dict):
                continue
            for key, value in _flatten(data):
                if not BUSINESS_IDENTIFIER_PATTERN.search(key):
                    continue
                if isinstance(value, (dict, list)):
                    continue
                rules.append(
                    BusinessRule(
                        rule_id=f"{config_path}::{key}",
                        description="",
                        literal_value=str(value),
                        source_kind="config_value",
                        evidence=[Evidence(file=config_path, line=1)],
                    )
                )
        return rules

    def _describe(self, rule: BusinessRule) -> str:
        prompt = (
            f"A business rule named '{rule.rule_id.split('::')[-1]}' has the literal value "
            f"'{rule.literal_value}' (source: {rule.source_kind}). Write ONE plain-English sentence "
            "describing what this rule most likely governs."
        )
        result = self.llm_client.complete_json(prompt, schema=_DESCRIPTION_SCHEMA)
        return result.get("description") or f"{rule.rule_id.split('::')[-1]} = {rule.literal_value}"


def _load_config_file(abs_path: str) -> dict | list | None:
    path = Path(abs_path)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    if suffix in {".yml", ".yaml"} and yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception:  # noqa: BLE001
            return None
    if path.name.startswith(".env"):
        result = {}
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("\"'")
        return result
    return None


def _flatten(data: dict, prefix: str = "") -> list[tuple[str, object]]:
    items: list[tuple[str, object]] = []
    for key, value in data.items():
        full_key = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            items.extend(_flatten(value, full_key))
        else:
            items.append((full_key, value))
    return items

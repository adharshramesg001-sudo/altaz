"""Domain Glossary Agent (LLD Section 6.3, Corner #7).

Extracts the product's own business vocabulary directly from identifiers,
DB columns, and comments -- entirely code-grounded, no market/strategy
inference involved. `occurrence_count` and `source_kinds` are computed
before any LLM call; the LLM writes only `definition`, and confidence
scales with occurrence breadth, not with how fluent the generated
definition sounds.

Feeds both the Business Case Gap Detector (Section 5, as CandidateSignal
context) and the Product Synthesis reasoning mode (Section 12.2, as the
vocabulary backbone of "what this product is about").
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.agents.shared.identifiers import split_identifier_words
from atlaz.llm.client import BaseLLMClient
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

# Generic programming vocabulary that would otherwise dominate the term
# list without saying anything about the *business*.
STOPLIST = frozenset(
    {
        "manager",
        "handler",
        "util",
        "utils",
        "helper",
        "base",
        "abstract",
        "factory",
        "builder",
        "service",
        "controller",
        "model",
        "config",
        "settings",
        "test",
        "tests",
        "main",
        "init",
        "impl",
        "wrapper",
        "adapter",
        "client",
        "response",
        "request",
        "data",
        "item",
        "value",
        "object",
        "type",
        "id",
        "name",
        "index",
        "list",
        "map",
        "set",
        "get",
        "run",
        "execute",
        "process",
    }
)

_DEFINITION_SCHEMA = {
    "type": "object",
    "properties": {"definition": {"type": "string"}},
    "required": ["definition"],
}


@dataclass(slots=True)
class TermOccurrence:
    source_kind: str  # "class_name" | "db_column" | "comment" | "enum_value"
    evidence: Evidence


@dataclass(slots=True)
class GlossaryTerm:
    term: str
    definition: str = ""
    occurrence_count: int = 0
    source_kinds: list[str] = field(default_factory=list)
    tier: Tier = Tier.INFERABLE
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)


class DomainGlossaryExtractor:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(self, parsed: list[ParsedModule], data_entities: list[DataEntity] | None = None) -> list[GlossaryTerm]:
        occurrences: dict[str, list[TermOccurrence]] = {}

        for module in parsed:
            for cls in module.classes:
                self._record(occurrences, cls.name, "class_name", Evidence(file=module.file_path, line=cls.line_start))
            for func in module.functions:
                self._record(
                    occurrences, func.name, "class_name", Evidence(file=module.file_path, line=func.line_start)
                )
            for comment in module.comments:
                for word in _split_words(comment.text):
                    self._record(occurrences, word, "comment", Evidence(file=module.file_path, line=comment.line))

        for entity in data_entities or []:
            entity_evidence = entity.evidence[0] if entity.evidence else Evidence.gap()
            self._record(occurrences, entity.entity_name, "db_column", entity_evidence)
            for field_info in entity.fields:
                self._record(occurrences, field_info.name, "db_column", entity_evidence)

        terms = []
        for term, occs in occurrences.items():
            if len(occs) < 2 and len({o.source_kind for o in occs}) < 2:
                continue  # a single, single-source occurrence is too weak to call a glossary term
            source_kinds = sorted({o.source_kind for o in occs})
            confidence = _confidence_from_signal(len(occs), len(source_kinds))
            terms.append(
                GlossaryTerm(
                    term=term,
                    occurrence_count=len(occs),
                    source_kinds=source_kinds,
                    confidence=confidence,
                    evidence=[o.evidence for o in occs[:5]],
                )
            )

        terms.sort(key=lambda t: t.occurrence_count, reverse=True)
        for term in terms:
            term.definition = self._define(term)
        return terms

    def _record(self, occurrences: dict[str, list[TermOccurrence]], raw_name: str, source_kind: str, evidence: Evidence) -> None:
        for word in _split_words(raw_name):
            if word in STOPLIST or len(word) < 3:
                continue
            occurrences.setdefault(word, []).append(TermOccurrence(source_kind=source_kind, evidence=evidence))

    def _define(self, term: GlossaryTerm) -> str:
        prompt = (
            f"The term '{term.term}' appears {term.occurrence_count} times in a codebase, as "
            f"{', '.join(term.source_kinds)}. Write one plain-English sentence defining what this term "
            "most likely means in this product's domain."
        )
        result = self.llm_client.complete_json(prompt, schema=_DEFINITION_SCHEMA)
        return result.get("definition") or f"'{term.term}' -- domain term inferred from code usage."


def _confidence_from_signal(occurrence_count: int, source_kind_count: int) -> float:
    """Confidence scales with occurrence breadth (count and source diversity),
    never with how fluent the LLM-generated definition sounds (LLD Section 6.3)."""
    count_component = min(occurrence_count / 5, 1.0) * 0.6
    diversity_component = min(source_kind_count / 3, 1.0) * 0.4
    return round(count_component + diversity_component, 3)


def _split_words(identifier: str) -> list[str]:
    return split_identifier_words(identifier, min_length=3)

"""Intended-vs-implemented conflict detection (LLD Section 9's `collect_node`:
"a BusinessRule literal_value that doesn't match a corresponding
DataEntity/APIContract value for the same concept").

"Same concept" is judged by shared business-vocabulary words between a
rule's identifier and a data entity field's name (restricted to the same
business-suggestive keyword set the Business Rule Extractor itself uses --
matching on generic words like "id" or "name" would produce false
conflicts). A conflict is only raised when the entity field also carries an
actual literal default to compare against; a field with no default has
nothing to disagree with.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlaz.agents.domain_b.business_rule_extractor import BUSINESS_IDENTIFIER_PATTERN, BusinessRule
from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.agents.shared.identifiers import split_identifier_words

_BUSINESS_CONCEPT_WORDS = frozenset(
    {"rate", "threshold", "limit", "fee", "tier", "cutoff", "quota", "discount", "penalty", "deadline", "max", "min"}
)


@dataclass(slots=True)
class ConflictCandidate:
    business_rule: BusinessRule
    data_entity: DataEntity
    field_name: str
    rule_value: str
    entity_value: str
    shared_concept_words: list[str]


def find_conflicts(rules: list[BusinessRule], entities: list[DataEntity]) -> list[ConflictCandidate]:
    conflicts: list[ConflictCandidate] = []
    for rule in rules:
        rule_identifier = rule.rule_id.rsplit("::", 1)[-1]
        if not BUSINESS_IDENTIFIER_PATTERN.search(rule_identifier):
            continue
        rule_words = set(split_identifier_words(rule_identifier)) & _BUSINESS_CONCEPT_WORDS

        for entity in entities:
            for entity_field in entity.fields:
                if entity_field.default_value is None:
                    continue
                field_words = set(split_identifier_words(entity_field.name)) & _BUSINESS_CONCEPT_WORDS
                shared = rule_words & field_words
                if not shared:
                    continue
                if _normalize(rule.literal_value) != _normalize(entity_field.default_value):
                    conflicts.append(
                        ConflictCandidate(
                            business_rule=rule,
                            data_entity=entity,
                            field_name=entity_field.name,
                            rule_value=rule.literal_value,
                            entity_value=entity_field.default_value,
                            shared_concept_words=sorted(shared),
                        )
                    )
    return conflicts


def _normalize(value: str) -> str:
    try:
        return str(float(value))
    except ValueError:
        return value.strip().lower()

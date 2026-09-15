"""Neo4j node/relationship schema (LLD Section 11).

`GraphNode`/`GraphEdge` are the language the orchestrator's
`graph_write_batch` speaks (LLD Section 9's `PipelineState`); the
`atlaz.graph_store.graph_builder` module is what actually produces them from
each domain's dataclass output, and `Neo4jWriter` is what commits them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeLabel(str, Enum):
    CAPABILITY = "Capability"
    BUSINESS_RULE = "BusinessRule"
    REQUIREMENT = "Requirement"
    COMPONENT = "Component"
    MODULE = "Module"
    DATA_ENTITY = "DataEntity"
    API_CONTRACT = "APIContract"
    TEST_CASE = "TestCase"
    SECURITY_CONTROL = "SecurityControl"
    GLOSSARY_TERM = "GlossaryTerm"
    GAP = "Gap"  # Domain A's business_case_vision node -- external-only, holds no code facts


class EdgeType(str, Enum):
    IMPLEMENTS = "implements"
    DEPENDS_ON = "depends_on"
    VALIDATES = "validates"
    DOCUMENTS = "documents"
    CONFLICTS_WITH = "conflicts_with"  # only ever created post-HITL resolution (Section 11)
    DERIVED_FROM = "derived_from"
    OWNS = "owns"


# The property used as each label's natural/unique key for MERGE -- re-running
# the pipeline on an updated repo updates `last_verified` rather than
# duplicating nodes (LLD Section 11: "Every node write is a MERGE, never a CREATE").
NATURAL_KEY_FIELD: dict[NodeLabel, str] = {
    NodeLabel.CAPABILITY: "name",
    NodeLabel.BUSINESS_RULE: "rule_id",
    NodeLabel.REQUIREMENT: "function_ref",
    NodeLabel.COMPONENT: "name",
    NodeLabel.MODULE: "file_path",
    NodeLabel.DATA_ENTITY: "entity_name",
    NodeLabel.API_CONTRACT: "route_method",  # composite: f"{route}::{method}"
    NodeLabel.TEST_CASE: "name",
    NodeLabel.SECURITY_CONTROL: "control_id",  # composite: f"{control_type}::{location}::{detail}"
    NodeLabel.GLOSSARY_TERM: "term",
    NodeLabel.GAP: "corner",
}


@dataclass(slots=True)
class GraphNode:
    label: NodeLabel
    key_value: str
    properties: dict = field(default_factory=dict)

    @property
    def key_field(self) -> str:
        return NATURAL_KEY_FIELD[self.label]


@dataclass(slots=True)
class GraphEdge:
    edge_type: EdgeType
    source_label: NodeLabel
    source_key: str
    target_label: NodeLabel
    target_key: str
    properties: dict = field(default_factory=dict)


CONSTRAINT_STATEMENTS: list[str] = [
    f"CREATE CONSTRAINT {label.value.lower()}_key IF NOT EXISTS "
    f"FOR (n:{label.value}) REQUIRE n.{key_field} IS UNIQUE"
    for label, key_field in NATURAL_KEY_FIELD.items()
]

INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX entity_tier IF NOT EXISTS FOR (n:DataEntity) ON (n.tier)",
    "CREATE INDEX rule_tier IF NOT EXISTS FOR (n:BusinessRule) ON (n.tier)",
    "CREATE INDEX component_name IF NOT EXISTS FOR (n:Component) ON (n.name)",
]

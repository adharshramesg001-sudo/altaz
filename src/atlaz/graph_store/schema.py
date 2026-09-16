"""Neo4j node/relationship schema (LLD Section 9, Section 14.2).

Technical graph (deterministic, no `confidence` needed -- parser output is
ground truth) + business graph (inferred, always carries provenance) +
bridge edges connecting the two, uniformly carrying the full provenance
payload (`confidence`/`evidence_ids`/`derivation_method`/`status`/
`scoring_weight_profile`/`source_domain`).

Two disclosed simplifications versus the LLD's illustrative §9/§14.2 schema,
made because this codebase's actual agents don't produce the underlying
data the LLD's fuller shape assumes:

- **No separate `Module` label.** The LLD's `Module` (folder-level
  container) and `Service` (HLD-derived boundary) would, in this codebase,
  both be built from the exact same source -- `HLDBuilder`'s
  `ComponentDiagram.components` (folder-topology grouping). Rather than
  duplicate one real concept into two graph nodes, `Service` plays both
  roles: `Repository -[:CONTAINS]-> Service -[:CONTAINS]-> File`.
- **`Event` is schema-only.** No agent in this build detects async
  events/pub-sub; the label and `PUBLISHES`/`CONSUMES` edge types are kept
  for schema completeness (a future agent can populate them) but
  `graph_builder` never emits one, matching the same "architecture only,
  not executed" treatment Domain E gets from the capability registry.

`Requirement`/`TestCase`/`SecurityControl` are this codebase's own
legitimate outputs (Domain C/D agents) beyond the LLD's illustrative
example schema, kept as-is from the prior build. `DEPENDS_ON` between
`Service` nodes is likewise a disclosed, valuable extension (call-graph
derived component coupling) the LLD's relationship list doesn't enumerate
but doesn't forbid either.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeLabel(str, Enum):
    # --- technical graph ---
    REPOSITORY = "Repository"
    SERVICE = "Service"  # folder/component boundary; see module docstring
    FILE = "File"
    CLASS = "Class"
    METHOD = "Method"
    INTERFACE = "Interface"
    TABLE = "Table"
    DATABASE = "Database"
    API = "API"
    EVENT = "Event"  # schema-only, never populated this build (see module docstring)

    # --- business graph ---
    BUSINESS_CAPABILITY = "BusinessCapability"
    FEATURE = "Feature"
    WORKFLOW = "Workflow"
    STEP = "Step"
    BUSINESS_RULE = "BusinessRule"
    DOMAIN_CONCEPT = "DomainConcept"
    GAP = "Gap"  # Domain A's business_case_vision node -- external-only, holds no code facts

    # --- codebase-specific extensions beyond the LLD's illustrative schema ---
    REQUIREMENT = "Requirement"
    TEST_CASE = "TestCase"
    SECURITY_CONTROL = "SecurityControl"


class EdgeType(str, Enum):
    # --- technical graph (no confidence -- deterministic) ---
    CONTAINS = "contains"
    DEFINES = "defines"
    CALLS = "calls"
    READS = "reads"
    WRITES = "writes"
    IMPLEMENTS_INTERFACE = "implements_interface"
    EXTENDS = "extends"
    IMPORTS = "imports"
    EXPOSES = "exposes"
    INVOKES = "invokes"
    OWNS = "owns"
    BELONGS_TO = "belongs_to"
    PUBLISHES = "publishes"
    CONSUMES = "consumes"
    DEPENDS_ON = "depends_on"  # Service<->Service; disclosed extension, see module docstring

    # --- business graph (carries confidence -- inferred) ---
    HAS_FEATURE = "has_feature"
    HAS_WORKFLOW = "has_workflow"
    HAS_STEP = "has_step"
    GOVERNED_BY = "governed_by"
    USES = "uses"
    RELATES_TO = "relates_to"
    HAS_GAP = "has_gap"

    # --- bridge edges (technical <-> business; always full provenance) ---
    IMPLEMENTED_BY = "implemented_by"
    REALIZED_BY = "realized_by"
    EXECUTES = "executes"

    # --- codebase-specific extensions ---
    IMPLEMENTS = "implements"  # Service -> BusinessCapability / Module -> Requirement (prior-build edge, kept)
    VALIDATES = "validates"
    DOCUMENTS = "documents"
    CONFLICTS_WITH = "conflicts_with"  # only ever created post cross-domain-conflict resolution
    DERIVED_FROM = "derived_from"

    # --- cross-repo only ---
    CALLS_SERVICE = "calls_service"  # Service -> Service; the one edge type whose two
    # endpoints may carry different repo_ids. Written by `atlaz.crossrepo`
    # via its own repo_id-qualified MATCH, never by the per-repo ingestion
    # pipeline / `Neo4jWriter.write_batch` (whose generic edge MATCH is
    # natural-key-only, unsafe once two repos are in play). Carries the
    # same provenance shape as bridge edges (confidence/evidence_ids/
    # derivation_method/status/scoring_weight_profile/source_domain) plus
    # `matched_on`; `status` starts "unconfirmed" -- no HITL review step
    # exists for these yet (documented, not silently missing).


# The property used as each label's natural/unique key for MERGE -- re-running
# the pipeline on an updated repo updates `last_verified` rather than
# duplicating nodes (every node write is a MERGE, never a CREATE).
NATURAL_KEY_FIELD: dict[NodeLabel, str] = {
    NodeLabel.REPOSITORY: "repo_id",
    NodeLabel.SERVICE: "service_id",
    NodeLabel.FILE: "file_id",
    NodeLabel.CLASS: "class_id",
    NodeLabel.METHOD: "method_id",
    NodeLabel.INTERFACE: "interface_id",
    NodeLabel.TABLE: "table_id",
    NodeLabel.DATABASE: "database_id",
    NodeLabel.API: "api_id",
    NodeLabel.EVENT: "event_id",
    NodeLabel.BUSINESS_CAPABILITY: "capability_id",
    NodeLabel.FEATURE: "feature_id",
    NodeLabel.WORKFLOW: "workflow_id",
    NodeLabel.STEP: "step_id",
    NodeLabel.BUSINESS_RULE: "rule_id",
    NodeLabel.DOMAIN_CONCEPT: "concept_id",
    NodeLabel.GAP: "gap_id",
    NodeLabel.REQUIREMENT: "function_ref",
    NodeLabel.TEST_CASE: "name",
    NodeLabel.SECURITY_CONTROL: "control_id",  # composite: f"{control_type}::{location}::{detail}"
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
    "CREATE INDEX method_reachability IF NOT EXISTS FOR (m:Method) ON (m.reachability)",
    "CREATE INDEX rule_status IF NOT EXISTS FOR (n:BusinessRule) ON (n.status)",
    "CREATE INDEX file_classification IF NOT EXISTS FOR (f:File) ON (f.classification)",
    "CREATE INDEX entity_tier IF NOT EXISTS FOR (n:Table) ON (n.tier)",
    "CREATE INDEX service_name IF NOT EXISTS FOR (n:Service) ON (n.name)",
]

# Bridge-edge property shape every IMPLEMENTED_BY/REALIZED_BY/EXECUTES edge
# carries uniformly (LLD Section 9.3, 14.2.2) -- exported so
# `graph_builder` can validate/build these consistently instead of hand
# rolling the property dict at each call site.
BRIDGE_EDGE_PROPERTY_KEYS = (
    "confidence",
    "evidence_ids",
    "derivation_method",
    "status",
    "scoring_weight_profile",
    "source_domain",
)

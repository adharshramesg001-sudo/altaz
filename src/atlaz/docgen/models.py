"""Data shapes for HLD/LLD generation -- one row per graph fact,
deliberately close to the Neo4j record shape rather than reusing the
pipeline's own agent dataclasses: this module reads a *finished* graph,
possibly in a separate process/run from the one that built it, so it must
not assume any in-memory pipeline state is available.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class RepositoryFact:
    repo_id: str = ""
    name: str = ""
    primary_languages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ServiceFact:
    service_id: str
    name: str
    architecture_style: str = ""
    module_count: int = 0


@dataclass(slots=True)
class ServiceDependency:
    source: str
    target: str
    call_count: int = 0


@dataclass(slots=True)
class ClassFact:
    class_id: str
    name: str
    file_id: str
    signature: str = ""


@dataclass(slots=True)
class MethodFact:
    method_id: str
    name: str
    file_id: str
    signature: str = ""
    return_type: str = ""
    reachability: str = "unknown_external"


@dataclass(slots=True)
class CapabilityFact:
    capability_id: str
    name: str
    confidence: float = 0.0
    cohesion_score: float = 0.0
    member_modules: list[str] = field(default_factory=list)
    needs_review: bool = False
    feature_ids: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowFact:
    workflow_id: str
    name: str
    confidence: float = 0.0
    feature_id: str = ""
    steps: list[str] = field(default_factory=list)


@dataclass(slots=True)
class BusinessRuleFact:
    rule_id: str
    description: str = ""
    literal_value: str = ""
    source_kind: str = ""
    status: str = "confirmed"
    confidence: float = 0.0
    needs_review: bool = False


@dataclass(slots=True)
class TableFact:
    table_id: str
    name: str
    source_kind: str = ""
    fields_json: str = "[]"
    confidence: float = 0.0
    relationships: list[tuple[str, str, str]] = field(default_factory=list)  # (target, kind, table_id)


@dataclass(slots=True)
class ApiFact:
    api_id: str
    route: str
    method: str
    handler_ref: str | None = None
    spec_source: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class SecurityControlFact:
    control_id: str
    control_type: str
    location: str
    detail: str
    regulation_hypothesis: str | None = None
    regulation_confidence: float | None = None


@dataclass(slots=True)
class DomainConceptFact:
    concept_id: str
    term: str
    definition: str = ""
    occurrence_count: int = 0


@dataclass(slots=True)
class GapFact:
    gap_id: str
    category: str = "business_case"
    status: str = "external_only"
    signal_found: bool = False
    still_open: bool = True


@dataclass(slots=True)
class RequirementFact:
    function_ref: str
    signature: str = ""
    inferred_behavior: str = ""
    confidence: float = 0.0
    tier: str = "inferable"


@dataclass(slots=True)
class ConflictFact:
    rule_id: str
    table_name: str
    status: str
    field_name: str = ""
    rule_value: str = ""
    table_value: str = ""


@dataclass(slots=True)
class ProjectFacts:
    thread_id: str
    repository: RepositoryFact
    services: list[ServiceFact] = field(default_factory=list)
    service_dependencies: list[ServiceDependency] = field(default_factory=list)
    service_files: dict[str, list[str]] = field(default_factory=dict)  # service name -> file paths
    classes: list[ClassFact] = field(default_factory=list)
    methods: list[MethodFact] = field(default_factory=list)
    file_classification_counts: dict[str, int] = field(default_factory=dict)
    capabilities: list[CapabilityFact] = field(default_factory=list)
    workflows: list[WorkflowFact] = field(default_factory=list)
    business_rules: list[BusinessRuleFact] = field(default_factory=list)
    tables: list[TableFact] = field(default_factory=list)
    apis: list[ApiFact] = field(default_factory=list)
    security_controls: list[SecurityControlFact] = field(default_factory=list)
    domain_concepts: list[DomainConceptFact] = field(default_factory=list)
    gaps: list[GapFact] = field(default_factory=list)
    requirements: list[RequirementFact] = field(default_factory=list)
    conflicts: list[ConflictFact] = field(default_factory=list)


@dataclass(slots=True)
class DocGenResult:
    project_id: str
    thread_id: str
    hld_markdown: str
    lld_markdown: str
    output_dir: Path | None = None

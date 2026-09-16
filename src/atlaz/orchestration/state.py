"""PipelineState (LLD Section 3).

Namespaced per domain (`DomainState` holds one distinct `TypedDict` per
domain, never a shared flat dict) -- the direct structural fix for the
"silent key collision" risk the LLD's own review flagged: two domains
cannot accidentally overwrite `confidence`/`evidence_ids` because each
domain's output is scoped under `state.domains.<domain>.*` until the single,
deliberate consolidation step (`score_confidence`/`detect_cross_domain_
conflicts`) reads across them.

Deliberately holds only picklable pipeline artifacts. `PipelineConfig`
(which carries the LLM API key) and the constructed `LLMClient`/agent
instances are never placed in this state: LangGraph checkpoints the state
to disk (SQLite), and a secret has no business sitting in a checkpoint file
on disk. The orchestration graph instead closes over config/clients when
nodes are built (see `atlaz.orchestration.graph.build_state_graph`).
"""

from __future__ import annotations

from typing import Annotated, Literal, TypedDict

from atlaz.agents.cross_domain.workflow_trace import WorkflowTrace
from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_a.readme_commit_signal_miner import CandidateSignal
from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.api_contract_parser import APIContract
from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.agents.domain_d.lld_parser import LLDEntry
from atlaz.agents.domain_d.security_control_scanner import SecurityControl
from atlaz.analysis.call_graph import CallGraph
from atlaz.analysis.config_schema_api import ConfigSchemaAPI
from atlaz.analysis.data_flow import DataFlow
from atlaz.analysis.dependency_graph import DependencyGraph
from atlaz.analysis.symbol_table import SymbolTable
from atlaz.graph_store.schema import GraphEdge, GraphNode
from atlaz.hitl.models import ReviewItem, ReviewResolution
from atlaz.ingestion.models import RepoInventory, RepoMeta
from atlaz.orchestration.capability_registry import CapabilityRegistry
from atlaz.orchestration.confidence import ConfidenceRecord
from atlaz.orchestration.conflicts import Conflict
from atlaz.orchestration.dispute_resolution import ResolvedClaim
from atlaz.parsing.models import ParsedModule


class DomainAOutput(TypedDict, total=False):
    signals: list[CandidateSignal]
    flagged_gaps: list[GapFinding]


class DomainBOutput(TypedDict, total=False):
    capability_clusters: list[CapabilityCluster]
    business_rules: list[BusinessRule]
    glossary_terms: list[GlossaryTerm]
    brd_extraction: None  # not built -- explicit null, not an absent key


class DomainCOutput(TypedDict, total=False):
    frd_claims: list[FunctionalRequirement]
    prd_inference: None  # not built -- explicit null, not an absent key


class DomainDOutput(TypedDict, total=False):
    hld: ComponentDiagram
    lld: list[LLDEntry]
    data_model: list[DataEntity]
    api: list[APIContract]
    security: list[SecurityControl]


DomainEOutput = None  # not executed -- entire subgraph descoped (LLD Section 7.5)


class DomainState(TypedDict, total=False):
    domain_a: DomainAOutput
    domain_b: DomainBOutput
    domain_c: DomainCOutput
    domain_d: DomainDOutput
    domain_e: DomainEOutput | None


def merge_domains(a: dict | None, b: dict | None) -> dict:
    """Reducer for `domains`: domain_a/b/c/d run as parallel `Send()`
    siblings dispatched together from `domain_orchestrator`, each returning
    a partial `{"domains": {"domain_x": ...}}` update against the same
    state key -- same concurrent-write situation as `ast_index`, same
    shallow-merge fix."""
    merged = dict(a or {})
    merged.update(b or {})
    return merged


def merge_ast_index(a: dict | None, b: dict | None) -> dict:
    """Reducer for `ast_index`: N4 (`parse_ast`) fans out one task per file
    via `Send()`, and every task returns a partial `{"ast_index": {path:
    module_or_none}}` update against the *same* state key -- LangGraph
    needs an explicit reducer to merge those concurrent partial updates
    rather than raising on the conflicting write."""
    merged = dict(a or {})
    merged.update(b or {})
    return merged


class WriteStatus(TypedDict, total=False):
    status: Literal["pending", "written", "skipped", "failed"]
    detail: str


class PipelineState(TypedDict, total=False):
    # --- run metadata ---
    run_id: str
    repo_path: str
    run_mode: Literal["full", "incremental"]
    changed_files: list[str] | None
    capability_registry: CapabilityRegistry

    # --- ingestion outputs (N1) ---
    repo_meta: RepoMeta
    inventory: RepoInventory  # full file listing; repo_meta is the graph-facing summary of it
    file_classification: dict[str, str]  # path -> "source"|"config"|"build"|"infra"|"docs"|"test"|"unknown"
    detected_languages: list[str]

    # --- deterministic analysis outputs (N4-N9) ---
    ast_index: Annotated[dict[str, ParsedModule | None], merge_ast_index]  # path -> parsed module, or None on parse_failed
    symbol_table: SymbolTable
    call_graph: CallGraph
    data_flow: DataFlow
    config_schema_api: ConfigSchemaAPI
    dependency_graph: DependencyGraph

    # --- domain outputs (namespaced per domain, never flat) ---
    domains: Annotated[DomainState, merge_domains]
    workflow_traces: list[WorkflowTrace]  # cross-domain (B+D); own namespace, not nested under either

    # --- cross-domain resolution ---
    cross_domain_conflicts: list[Conflict]
    consolidated_business_rules: list[BusinessRule]

    # --- confidence + dispute resolution ---
    confidence_scores: dict[str, ConfidenceRecord]  # claim_id -> record
    disputes: list[Conflict]
    resolved_claims: list[ResolvedClaim]

    # --- write-stage tracking ---
    kg_write_status: WriteStatus
    vector_write_status: WriteStatus
    evidence_write_status: WriteStatus

    # --- loop control (incremental re-analysis, LLD Section 12) ---
    pending_files: list[str]

    # --- three-tier HITL review (gap confirmation / low-confidence / value-mismatch
    # conflict), kept from the prior design -- orthogonal to the N11X cross-domain
    # conflict/dispute-resolution path above ---
    flagged_for_review: list[ReviewItem]
    hitl_resolutions: list[ReviewResolution]

    # --- graph write batch, built by prepare_graph_batch from every artifact above ---
    graph_write_nodes: list[GraphNode]
    graph_write_edges: list[GraphEdge]

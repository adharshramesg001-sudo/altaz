"""PipelineState (LLD Section 9).

Deliberately holds only picklable pipeline artifacts -- inventory, parsed
modules, domain outputs, flagged items, resolutions, the graph write batch.
`PipelineConfig` (which carries the LLM API key) and the constructed
`LLMClient`/agent instances are never placed in this state: LangGraph
checkpoints the state to disk (SQLite for this build, per LLD Section 13.1),
and a secret has no business sitting in a checkpoint file on disk. The
orchestration graph instead closes over config/clients when nodes are built
(see `atlaz.orchestration.graph.build_graph`).
"""

from __future__ import annotations

from typing import TypedDict

from atlaz.agents.domain_a.gap_detector import GapFinding
from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.api_contract_parser import APIContract
from atlaz.agents.domain_d.data_model_extractor import DataEntity
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.agents.domain_d.lld_parser import LLDEntry
from atlaz.agents.domain_d.security_control_scanner import SecurityControl
from atlaz.graph_store.schema import GraphEdge, GraphNode
from atlaz.hitl.models import ReviewItem, ReviewResolution
from atlaz.ingestion.models import RepoInventory
from atlaz.parsing.models import ParsedModule


class DomainBOutput(TypedDict):
    capability_clusters: list[CapabilityCluster]
    business_rules: list[BusinessRule]
    glossary_terms: list[GlossaryTerm]


class DomainDOutput(TypedDict):
    hld: ComponentDiagram
    lld: list[LLDEntry]
    data_model: list[DataEntity]
    api: list[APIContract]
    security: list[SecurityControl]


class PipelineState(TypedDict, total=False):
    repo_path: str
    inventory: RepoInventory
    parsed_modules: list[ParsedModule]

    domain_a: GapFinding
    domain_b: DomainBOutput
    domain_c: list[FunctionalRequirement]
    domain_d: DomainDOutput

    flagged_for_review: list[ReviewItem]
    hitl_resolutions: list[ReviewResolution]

    graph_write_nodes: list[GraphNode]
    graph_write_edges: list[GraphEdge]

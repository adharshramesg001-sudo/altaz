"""LangGraph node functions for the full N1-N21 pipeline (LLD Section 4's
topology).

Two scheduling simplifications versus the LLD's literal diagram, both
disclosed and both chosen to keep this build's `Send()`-based fan-out
correct and verifiable rather than merely diagram-shaped:

- **N2/N3D/N3 are one routing function.** `route_and_fan_out_files`
  combines "incremental run?", `fan_out_changed_files`, and
  `fan_out_files` into a single conditional-edge function attached to
  `ingest_repo`: it decides full-vs-delta scope and returns the `Send()`
  list in one step. The three are pure data-scoping decisions with no
  independent computation between them, so collapsing them costs nothing
  semantically.
- **Domain fan-out is per-domain, not per-agent.** `domain_orchestrator`
  dispatches one `Send()` per enabled *domain* (`domain_a`..`domain_d`);
  each domain's node function is what enforces per-agent gating
  (`registry[domain][agent]`) before calling that agent's code. All four
  domains are dispatched together (siblings of the same `Send()` call), so
  they land in the same LangGraph superstep -- this is what lets
  `workflow_trace` (which needs Domain B's clusters *and* Domain D's HLD)
  have a single, correctly-synchronized fan-in from all four, without a
  hand-rolled passthrough node to equalize otherwise-mismatched path
  lengths. The trade-off: Domain A's `readme_commit_signal_miner` no
  longer sees Domain B's glossary (it used to run strictly after Domain B)
  -- its `naming_pattern` signal source is simply empty in this ordering,
  a documented quality loss, not a correctness one.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from langgraph.types import Send

from atlaz.agents.cross_domain.workflow_trace import build_workflow_traces
from atlaz.agents.domain_a.gap_detector import BusinessCaseGapDetector
from atlaz.agents.domain_a.readme_commit_signal_miner import ReadmeCommitSignalMiner
from atlaz.agents.domain_b.business_rule_extractor import BusinessRuleExtractor
from atlaz.agents.domain_b.capability_clustering import CapabilityClusterer
from atlaz.agents.domain_b.domain_glossary import DomainGlossaryExtractor
from atlaz.agents.domain_c.frd_extractor import FRDExtractor
from atlaz.agents.domain_d.hld_builder import ComponentDiagram, HLDBuilder
from atlaz.agents.domain_d.lld_parser import LLDParser
from atlaz.agents.domain_d.security_control_scanner import SecurityControlScanner
from atlaz.analysis.call_graph import build_call_graph
from atlaz.analysis.config_schema_api import analyze_config_schema_api
from atlaz.analysis.data_flow import analyze_data_flow
from atlaz.analysis.dependency_graph import merge_dependency_graph
from atlaz.analysis.file_classification import classify_inventory
from atlaz.analysis.symbol_table import build_symbol_table
from atlaz.audit.models import ConflictRecord, EvidenceRecord, ParseFailure
from atlaz.audit.repository import record_conflicts, record_evidence, record_parse_failures
from atlaz.enhancement.guideline_store import default_embed_fn
from atlaz.graph_store import graph_builder
from atlaz.graph_store.neo4j_writer import Neo4jWriter
from atlaz.graph_store.schema import GraphEdge, GraphNode
from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.hitl.merge import collect_flagged_items
from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewResolution
from atlaz.hitl.resolution_application import apply_low_confidence_resolutions, find_gap_resolution
from atlaz.ingestion.models import RepoMeta
from atlaz.ingestion.repo_ingestor import RepoIngestor
from atlaz.llm.client import BaseLLMClient
from atlaz.orchestration.capability_registry import (
    CapabilityRegistry,
    enabled_domains,
    validate_capability_registry,
)
from atlaz.orchestration.confidence import Claim, score_claim
from atlaz.orchestration.conflicts import Conflict, detect_conflicts
from atlaz.orchestration.dispute_resolution import accept_resolved as accept_resolved_claims
from atlaz.orchestration.dispute_resolution import auto_resolve_dispute as resolve_one_dispute
from atlaz.parsing.parser_registry import ParserRegistry
from atlaz.shared.config import PipelineConfig
from atlaz.vector_store.qdrant_writer import (
    BUSINESS_RULE,
    CODE,
    DOC,
    FEATURE,
    GLOSSARY,
    QdrantVectorIndex,
    VectorDocument,
    write_documents,
)

logger = logging.getLogger(__name__)

# Agent identifiers `check_capability_registry` validates the YAML against
# -- see `orchestration.capability_registry`'s module docstring for why
# this, not literal LangGraph node names, is this build's validation unit.
IMPLEMENTED_AGENTS = {
    "domain_a.readme_commit_signal_miner",
    "domain_a.gap_detector",
    "domain_b.capability_clustering",
    "domain_b.business_rule_extraction",
    "domain_b.domain_glossary_builder",
    "domain_c.frd_extraction",
    "domain_d.hld_builder",
    "domain_d.lld_parser",
    "domain_d.data_model_extractor",
    "domain_d.api_contract_parser",
    "domain_d.security_control_scanner",
}


def _parsed_modules(state) -> list:
    return [m for m in state.get("ast_index", {}).values() if m is not None]


# --- N1: ingest_repo ---------------------------------------------------


def make_ingest_repo_node(config: PipelineConfig):
    def ingest_repo_node(state):
        logger.info("[ingest_repo] scanning repo_path=%s", state["repo_path"])
        inventory = RepoIngestor(ignore_dirs=frozenset(config.ignore_dirs)).ingest(state["repo_path"])
        file_classification = classify_inventory(inventory)
        detected_languages = sorted({f.language for f in inventory.files if f.language})
        repo_meta = RepoMeta(repo_id=inventory.repo_id, name=inventory.repo_id, primary_languages=detected_languages)
        logger.info("[ingest_repo] found %d file(s), %d language(s)", len(inventory.files), len(detected_languages))
        return {
            "inventory": inventory,
            "repo_meta": repo_meta,
            "file_classification": file_classification,
            "detected_languages": detected_languages,
        }

    return ingest_repo_node


# --- N2/N3D/N3: incremental routing + file fan-out ----------------------


def route_and_fan_out_files(state):
    inventory = state["inventory"]
    changed: set[str] | None = None
    if state.get("run_mode") == "incremental":
        changed = set(state.get("changed_files") or [])
        logger.info("[fan_out_files] incremental run: %d changed file(s)", len(changed))

    sends = []
    for f in inventory.files:
        if not f.language:
            continue
        if changed is not None and f.path not in changed:
            continue
        sends.append(Send("parse_ast", {"repo_root": inventory.repo_root, "file_record": f}))

    if not sends:
        return "build_symbol_table"  # nothing to parse -- skip straight to the (empty) fan-in
    return sends


# --- N4: parse_ast (Send() target, one invocation per file) -------------


def parse_ast_node(payload):
    file_record = payload["file_record"]
    repo_root = payload["repo_root"]
    try:
        parser = ParserRegistry().resolve(file_record.language, file_path=file_record.path)
        module = parser.parse_file(file_record, repo_root)
        return {"ast_index": {file_record.path: module}}
    except Exception as exc:  # noqa: BLE001 - one bad file must never abort the fan-in
        logger.warning("[parse_ast] failed for %s: %s", file_record.path, exc)
        return {"ast_index": {file_record.path: None}}


# --- N5-N9: deterministic analysis stage ---------------------------------


def build_symbol_table_node(state):
    table = build_symbol_table(_parsed_modules(state))
    logger.info("[build_symbol_table] %d symbol(s)", len(table.symbols))
    return {"symbol_table": table}


def build_call_graph_node(state):
    graph = build_call_graph(_parsed_modules(state), state["symbol_table"])
    logger.info("[build_call_graph] %d edge(s)", len(graph.edges))
    return {"call_graph": graph}


def analyze_data_flow_node(state):
    flow = analyze_data_flow(_parsed_modules(state), state["symbol_table"])
    return {"data_flow": flow}


def analyze_config_schema_api_node(state):
    result = analyze_config_schema_api(state["inventory"], _parsed_modules(state))
    logger.info(
        "[analyze_config_schema_api] %d data entity(ies), %d API contract(s)",
        len(result.data_entities), len(result.api_contracts),
    )
    return {"config_schema_api": result}


def merge_dependency_graph_node(state):
    dependency_graph = merge_dependency_graph(
        state["symbol_table"], state["call_graph"], state["data_flow"], state["config_schema_api"]
    )
    return {"dependency_graph": dependency_graph}


# --- N10/N10ORCH: capability registry + domain fan-out -------------------


def make_check_capability_registry_node(registry: CapabilityRegistry):
    def check_capability_registry_node(state):
        validate_capability_registry(registry, IMPLEMENTED_AGENTS)
        return {"capability_registry": registry}

    return check_capability_registry_node


def make_domain_orchestrator(registry: CapabilityRegistry):
    domains_to_dispatch = [d for d in ("domain_a", "domain_b", "domain_c", "domain_d") if d in enabled_domains(registry)]

    def domain_orchestrator(state):
        if not domains_to_dispatch:
            return "workflow_trace"
        return [Send(d, state) for d in domains_to_dispatch]

    return domain_orchestrator


# --- Domain subgraphs (one LangGraph node per domain) --------------------


def make_domain_a_node(registry: CapabilityRegistry):
    def domain_a_node(state):
        agents = registry.get("domain_a", {})
        parsed = _parsed_modules(state)
        signals = []
        if agents.get("readme_commit_signal_miner"):
            glossary = state.get("domains", {}).get("domain_b", {}).get("glossary_terms", [])
            signals = ReadmeCommitSignalMiner().run(state["inventory"], parsed, glossary)
        flagged_gaps = []
        if agents.get("gap_detector"):
            flagged_gaps = [BusinessCaseGapDetector().run(signals)]
        logger.info("[domain_a] %d signal(s), %d gap(s)", len(signals), len(flagged_gaps))
        return {"domains": {"domain_a": {"signals": signals, "flagged_gaps": flagged_gaps}}}

    return domain_a_node


def make_domain_b_node(llm_client: BaseLLMClient, confidence_threshold: float, registry: CapabilityRegistry):
    def domain_b_node(state):
        agents = registry.get("domain_b", {})
        parsed = _parsed_modules(state)
        inventory = state["inventory"]
        data_entities = state["config_schema_api"].data_entities
        clusters = CapabilityClusterer(llm_client, confidence_threshold).run(parsed) if agents.get("capability_clustering") else []
        rules = BusinessRuleExtractor(llm_client).run(inventory) if agents.get("business_rule_extraction") else []
        glossary = (
            DomainGlossaryExtractor(llm_client).run(parsed, data_entities) if agents.get("domain_glossary_builder") else []
        )
        logger.info(
            "[domain_b] %d cluster(s), %d rule(s), %d glossary term(s)", len(clusters), len(rules), len(glossary)
        )
        return {
            "domains": {
                "domain_b": {
                    "capability_clusters": clusters,
                    "business_rules": rules,
                    "glossary_terms": glossary,
                    "brd_extraction": None,
                }
            }
        }

    return domain_b_node


def make_domain_c_node(llm_client: BaseLLMClient, registry: CapabilityRegistry):
    def domain_c_node(state):
        agents = registry.get("domain_c", {})
        parsed = _parsed_modules(state)
        requirements = FRDExtractor(llm_client).run(parsed) if agents.get("frd_extraction") else []
        logger.info("[domain_c] %d functional requirement(s)", len(requirements))
        return {"domains": {"domain_c": {"frd_claims": requirements, "prd_inference": None}}}

    return domain_c_node


def make_domain_d_node(llm_client: BaseLLMClient, registry: CapabilityRegistry):
    def domain_d_node(state):
        agents = registry.get("domain_d", {})
        parsed = _parsed_modules(state)
        config_schema_api = state["config_schema_api"]
        hld = HLDBuilder(llm_client).run(parsed) if agents.get("hld_builder") else ComponentDiagram()
        lld = LLDParser().run(parsed) if agents.get("lld_parser") else []
        security = (
            SecurityControlScanner(llm_client).run(parsed, config_schema_api.data_entities)
            if agents.get("security_control_scanner")
            else []
        )
        data_model = config_schema_api.data_entities if agents.get("data_model_extractor") else []
        api = config_schema_api.api_contracts if agents.get("api_contract_parser") else []
        logger.info(
            "[domain_d] hld=%d component(s), %d lld entry(ies), %d security control(s)",
            len(hld.components), len(lld), len(security),
        )
        return {"domains": {"domain_d": {"hld": hld, "lld": lld, "data_model": data_model, "api": api, "security": security}}}

    return domain_d_node


def workflow_trace_node(state):
    domains = state.get("domains", {})
    clusters = domains.get("domain_b", {}).get("capability_clusters", [])
    hld = domains.get("domain_d", {}).get("hld") or ComponentDiagram()
    traces = build_workflow_traces(clusters, hld, state["call_graph"], state["symbol_table"])
    logger.info("[workflow_trace] %d trace(s)", len(traces))
    return {"workflow_traces": traces}


def collect_domain_outputs_node(state):
    """N11: pure aggregation fan-in -- every domain already wrote directly
    into `state.domains.*`/`state.workflow_traces`; this node exists as the
    documented convergence point, not to transform anything."""
    return {}


# --- Three-tier HITL gate (gap confirmation / low-confidence finding) ----


def make_collect_flagged_items_node(confidence_threshold: float):
    def collect_flagged_items_node(state):
        domains = state.get("domains", {})
        domain_b = domains.get("domain_b", {})
        domain_c = domains.get("domain_c", {})
        domain_d = domains.get("domain_d", {})
        items = collect_flagged_items(
            flagged_gaps=domains.get("domain_a", {}).get("flagged_gaps", []),
            capability_clusters=domain_b.get("capability_clusters", []),
            glossary_terms=domain_b.get("glossary_terms", []),
            functional_requirements=domain_c.get("frd_claims", []),
            component_diagram=domain_d.get("hld") or ComponentDiagram(),
            security_controls=domain_d.get("security", []),
            confidence_threshold=confidence_threshold,
        )
        logger.info("[collect_flagged_items] %d item(s) flagged for review", len(items))
        return {"flagged_for_review": items}

    return collect_flagged_items_node


def route_after_collect(state) -> str:
    return "hitl_gate" if state.get("flagged_for_review") else "apply_hitl_resolutions"


def make_hitl_gate_node(config: PipelineConfig, interrupt_fn):
    def hitl_gate_node(state):
        flagged: list[ReviewItem] = state["flagged_for_review"]
        if config.hitl_enabled:
            logger.info("[hitl_gate] HITL enabled; interrupting for %d flagged item(s)", len(flagged))
            resolutions: list[ReviewResolution] = interrupt_fn(flagged)
        else:
            logger.info("[hitl_gate] HITL disabled; auto-resolving %d flagged item(s)", len(flagged))
            resolutions = auto_resolve(flagged)
        return {"hitl_resolutions": resolutions}

    return hitl_gate_node


def apply_hitl_resolutions_node(state):
    """Folds `hitl_resolutions` back into `state.domains.*` in place --
    everything downstream (conflict detection, scoring, graph write) reads
    the post-resolution values."""
    flagged: list[ReviewItem] = state.get("flagged_for_review", [])
    resolutions: list[ReviewResolution] = state.get("hitl_resolutions", [])
    if not flagged and not resolutions:
        return {}

    domains = dict(state.get("domains", {}))
    domain_b = dict(domains.get("domain_b", {}))
    domain_c = dict(domains.get("domain_c", {}))
    domain_d = dict(domains.get("domain_d", {}))

    domain_b["capability_clusters"] = apply_low_confidence_resolutions(
        domain_b.get("capability_clusters", []), flagged, resolutions
    )
    domain_b["glossary_terms"] = apply_low_confidence_resolutions(domain_b.get("glossary_terms", []), flagged, resolutions)
    domain_c["frd_claims"] = apply_low_confidence_resolutions(domain_c.get("frd_claims", []), flagged, resolutions)
    diagram_list = apply_low_confidence_resolutions([domain_d.get("hld") or ComponentDiagram()], flagged, resolutions)
    domain_d["hld"] = diagram_list[0] if diagram_list else domain_d.get("hld")
    domain_d["security"] = apply_low_confidence_resolutions(domain_d.get("security", []), flagged, resolutions)

    domains["domain_b"] = domain_b
    domains["domain_c"] = domain_c
    domains["domain_d"] = domain_d
    return {"domains": domains}


# --- N11X-N13: cross-domain conflict detection + confidence scoring ------


def _module_reachable(file_path: str, symbol_table, call_graph) -> bool:
    called = {e.callee for e in call_graph.edges if e.resolution == "static"}
    file_symbols = {qn for qn, entry in symbol_table.symbols.items() if entry.file_path == file_path}
    return bool(file_symbols & called) or not file_symbols


def _build_conflict_claims(state) -> list[Claim]:
    domains = state.get("domains", {})
    symbol_table = state.get("symbol_table")
    call_graph = state.get("call_graph")
    claims: list[Claim] = []

    domain_b = domains.get("domain_b", {})
    for cluster in domain_b.get("capability_clusters", []):
        for module in cluster.member_modules:
            claims.append(
                Claim(
                    claim_id=f"domain_b.capability_clustering::{cluster.capability_name}::{module}",
                    domain="domain_b",
                    entity_id=module,
                    raw_confidence=cluster.confidence,
                    assertion={"kind": "capability_membership", "active": True, "capability_name": cluster.capability_name},
                )
            )
            claims.append(
                Claim(
                    claim_id=f"domain_b.capability_clustering::purpose::{cluster.capability_name}::{module}",
                    domain="domain_b",
                    entity_id=module,
                    raw_confidence=cluster.confidence,
                    assertion={"kind": "purpose", "purpose_text": cluster.capability_name},
                )
            )

    if symbol_table is not None and call_graph is not None:
        files = {entry.file_path for entry in symbol_table.symbols.values()}
        for file_path in files:
            claims.append(
                Claim(
                    claim_id=f"domain_d.hld_builder::reachability::{file_path}",
                    domain="domain_d",
                    entity_id=file_path,
                    raw_confidence=0.85,
                    assertion={"kind": "reachability", "reachable": _module_reachable(file_path, symbol_table, call_graph)},
                )
            )

    domain_c = domains.get("domain_c", {})
    for req in domain_c.get("frd_claims", []):
        file_path = req.evidence[0].file if req.evidence else None
        if not file_path:
            continue
        claims.append(
            Claim(
                claim_id=f"domain_c.frd_extraction::{req.function_ref}",
                domain="domain_c",
                entity_id=file_path,
                raw_confidence=req.confidence,
                assertion={"kind": "purpose", "purpose_text": req.inferred_behavior},
            )
        )

    return claims


def detect_cross_domain_conflicts_node(state):
    claims = _build_conflict_claims(state)
    business_rules = state.get("domains", {}).get("domain_b", {}).get("business_rules", [])
    data_entities = state["config_schema_api"].data_entities
    conflicts = detect_conflicts(claims, business_rules, data_entities)
    logger.info("[detect_cross_domain_conflicts] %d conflict(s)", len(conflicts))
    return {"cross_domain_conflicts": conflicts}


def consolidate_business_rules_node(state):
    rules = state.get("domains", {}).get("domain_b", {}).get("business_rules", [])
    deduped: dict[str, object] = {}
    for rule in rules:
        deduped[rule.rule_id] = rule
    return {"consolidated_business_rules": list(deduped.values())}


def _build_scoring_claims(state) -> list[Claim]:
    domains = state.get("domains", {})
    workflow_traces = state.get("workflow_traces", [])
    workflow_capability_names = {t.capability_name for t in workflow_traces if t.capability_name}
    claims: list[Claim] = []

    for gap in domains.get("domain_a", {}).get("flagged_gaps", []):
        claims.append(
            Claim(
                claim_id=f"domain_a.gap_detector::{gap.corner}",
                domain="domain_a",
                entity_id=gap.corner,
                raw_confidence=0.0,
                evidence_ids=[f"{e.file}:{e.line}" for e in gap.evidence if e.file],
                signal_count=len(gap.candidate_signals),
                distinct_source_kinds=len({s.source_kind for s in gap.candidate_signals}),
            )
        )

    domain_b = domains.get("domain_b", {})
    for cluster in domain_b.get("capability_clusters", []):
        corroborating = {"domain_b"}
        if cluster.capability_name in workflow_capability_names:
            corroborating.add("domain_d")
        claims.append(
            Claim(
                claim_id=f"domain_b.capability_clustering::{cluster.capability_name}",
                domain="domain_b",
                entity_id=cluster.capability_name,
                raw_confidence=cluster.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in cluster.evidence if e.file],
                structural_signal=cluster.cohesion_score,
                corroborating_domains=frozenset(corroborating),
            )
        )
    for rule in domain_b.get("business_rules", []):
        claims.append(
            Claim(
                claim_id=f"domain_b.business_rule_extraction::{rule.rule_id}",
                domain="domain_b",
                entity_id=rule.rule_id,
                raw_confidence=rule.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in rule.evidence if e.file],
            )
        )
    for term in domain_b.get("glossary_terms", []):
        claims.append(
            Claim(
                claim_id=f"domain_b.domain_glossary_builder::{term.term}",
                domain="domain_b",
                entity_id=term.term,
                raw_confidence=term.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in term.evidence if e.file],
            )
        )

    for req in domains.get("domain_c", {}).get("frd_claims", []):
        claims.append(
            Claim(
                claim_id=f"domain_c.frd_extraction::{req.function_ref}",
                domain="domain_c",
                entity_id=req.function_ref,
                raw_confidence=req.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in req.evidence if e.file],
            )
        )

    domain_d = domains.get("domain_d", {})
    hld = domain_d.get("hld")
    if hld is not None and hld.components:
        claims.append(
            Claim(
                claim_id="domain_d.hld_builder::architecture_style",
                domain="domain_d",
                entity_id="architecture_style",
                raw_confidence=hld.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in hld.evidence if e.file],
            )
        )
    for entity in domain_d.get("data_model", []):
        claims.append(
            Claim(
                claim_id=f"domain_d.data_model_extractor::{entity.entity_name}",
                domain="domain_d",
                entity_id=entity.entity_name,
                raw_confidence=entity.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in entity.evidence if e.file],
            )
        )
    for contract in domain_d.get("api", []):
        claims.append(
            Claim(
                claim_id=f"domain_d.api_contract_parser::{contract.route}::{contract.method}",
                domain="domain_d",
                entity_id=f"{contract.route}::{contract.method}",
                raw_confidence=contract.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in contract.evidence if e.file],
            )
        )
    for control in domain_d.get("security", []):
        control_id = f"{control.control_type}::{control.location}::{control.detail}"[:512]
        claims.append(
            Claim(
                claim_id=f"domain_d.security_control_scanner::{control_id}",
                domain="domain_d",
                entity_id=control_id,
                raw_confidence=control.confidence,
                evidence_ids=[f"{e.file}:{e.line}" for e in control.evidence if e.file],
            )
        )

    return claims


def score_confidence_node(state):
    claims = _build_scoring_claims(state)
    records = {claim.claim_id: score_claim(claim) for claim in claims}
    logger.info("[score_confidence] scored %d claim(s)", len(records))
    return {"confidence_scores": records}


# --- N14-N16: dispute routing + resolution --------------------------------


def route_dispute(state) -> str:
    return "auto_resolve_dispute" if state.get("cross_domain_conflicts") else "accept_resolved"


def auto_resolve_dispute_node(state):
    conflicts: list[Conflict] = state.get("cross_domain_conflicts", [])
    confidence_by_claim_id = {claim_id: record.confidence for claim_id, record in state.get("confidence_scores", {}).items()}
    resolved = []
    for conflict in conflicts:
        resolved.extend(resolve_one_dispute(conflict, confidence_by_claim_id))
    logger.info("[auto_resolve_dispute] resolved %d claim(s) across %d conflict(s)", len(resolved), len(conflicts))
    return {"disputes": conflicts, "resolved_claims": resolved}


def accept_resolved_node(state):
    confidence_records = list(state.get("confidence_scores", {}).values())
    disputed_resolutions = state.get("resolved_claims", [])
    disputed_claim_ids = {r.claim_id for r in disputed_resolutions}
    final = accept_resolved_claims(confidence_records, disputed_claim_ids, disputed_resolutions)
    return {"resolved_claims": final}


# --- N17: write_knowledge_graph -------------------------------------------


def build_graph_batch(state, confidence_threshold: float) -> tuple[list[GraphNode], list[GraphEdge]]:
    repo_meta = state["repo_meta"]
    inventory = state["inventory"]
    symbol_table = state["symbol_table"]
    call_graph = state["call_graph"]
    config_schema_api = state["config_schema_api"]
    domains = state.get("domains", {})
    domain_a = domains.get("domain_a", {})
    domain_b = domains.get("domain_b", {})
    domain_c = domains.get("domain_c", {})
    domain_d = domains.get("domain_d", {})

    clusters = domain_b.get("capability_clusters", [])
    rules = state.get("consolidated_business_rules") or domain_b.get("business_rules", [])
    glossary = domain_b.get("glossary_terms", [])
    requirements = domain_c.get("frd_claims", [])
    hld = domain_d.get("hld") or ComponentDiagram()
    security = domain_d.get("security", [])
    gaps = domain_a.get("flagged_gaps", [])
    workflow_traces = state.get("workflow_traces", [])
    resolved_claims = state.get("resolved_claims", [])
    resolved_by_claim_id = {r.claim_id: r for r in resolved_claims}
    flagged = state.get("flagged_for_review", [])
    hitl_resolutions = state.get("hitl_resolutions", [])

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    nodes.append(graph_builder.build_repository_node(repo_meta.repo_id, repo_meta.name, repo_meta.primary_languages))
    nodes.extend(graph_builder.build_file_nodes(inventory, state.get("file_classification", {})))

    service_nodes, service_edges = graph_builder.build_service_nodes_and_edges(repo_meta.repo_id, hld)
    nodes.extend(service_nodes)
    edges.extend(service_edges)

    class_nodes, method_nodes = graph_builder.build_class_and_method_nodes(symbol_table, domain_d.get("lld", []))
    graph_builder.apply_reachability(method_nodes, call_graph)
    nodes.extend(class_nodes)
    nodes.extend(method_nodes)
    edges.extend(graph_builder.build_defines_and_calls_edges(symbol_table, call_graph))

    table_nodes, table_edges = graph_builder.build_table_and_database_nodes_and_edges(
        repo_meta.repo_id, config_schema_api, hld, confidence_threshold
    )
    nodes.extend(table_nodes)
    edges.extend(table_edges)

    api_nodes, api_edges = graph_builder.build_api_nodes_and_edges(config_schema_api, hld, confidence_threshold)
    nodes.extend(api_nodes)
    edges.extend(api_edges)

    nodes.extend(graph_builder.build_business_capability_nodes(clusters, confidence_threshold))
    feature_nodes, feature_edges = graph_builder.build_feature_nodes_and_edges(clusters)
    nodes.extend(feature_nodes)
    edges.extend(feature_edges)
    edges.extend(graph_builder.build_feature_implemented_by_edges(clusters, hld))

    workflow_nodes, step_nodes, workflow_edges = graph_builder.build_workflow_nodes_and_edges(workflow_traces)
    nodes.extend(workflow_nodes)
    nodes.extend(step_nodes)
    edges.extend(workflow_edges)

    nodes.extend(graph_builder.build_business_rule_nodes(rules, confidence_threshold, resolved_by_claim_id))
    edges.extend(graph_builder.build_business_rule_implemented_by_edges(rules, symbol_table))

    nodes.extend(graph_builder.build_domain_concept_nodes(glossary, confidence_threshold))

    capability_names = [c.capability_name for c in clusters]
    gap_resolution = find_gap_resolution(flagged, hitl_resolutions)
    resolution_answer = None
    if gap_resolution is not None and gap_resolution.action in (ReviewAction.ACCEPT, ReviewAction.EDIT):
        resolution_answer = gap_resolution.resolved_value
    for gap in gaps:
        gap_node, gap_edges = graph_builder.build_gap_node_and_edges(gap, resolution_answer, capability_names)
        nodes.append(gap_node)
        edges.extend(gap_edges)

    nodes.extend(graph_builder.build_requirement_nodes(requirements, confidence_threshold))
    test_nodes, test_edges = graph_builder.build_test_case_nodes_and_edges(requirements)
    nodes.extend(test_nodes)
    edges.extend(test_edges)
    edges.extend(graph_builder.build_requirement_implemented_by_edges(requirements))

    nodes.extend(graph_builder.build_security_control_nodes(security, confidence_threshold))

    edges.extend(graph_builder.build_conflict_edges(state.get("cross_domain_conflicts", []), resolved_by_claim_id))

    return nodes, edges


def make_write_knowledge_graph_node(config: PipelineConfig, writer_factory=None):
    writer_factory = writer_factory or (lambda: Neo4jWriter(config.neo4j))

    def write_knowledge_graph_node(state):
        nodes, edges = build_graph_batch(state, config.confidence_threshold)
        repo_id = state["repo_meta"].repo_id
        logger.info("[write_knowledge_graph] writing %d node(s), %d edge(s) for repo_id=%s", len(nodes), len(edges), repo_id)
        with writer_factory() as writer:
            writer.ensure_schema()
            writer.write_batch(nodes, edges, repo_id=repo_id)
        return {
            "graph_write_nodes": nodes,
            "graph_write_edges": edges,
            "kg_write_status": {"status": "written", "detail": f"{len(nodes)} node(s), {len(edges)} edge(s)"},
        }

    return write_knowledge_graph_node


# --- N18: write_vector_index ----------------------------------------------


def _build_vector_documents(state) -> list[VectorDocument]:
    docs: list[VectorDocument] = []
    domains = state.get("domains", {})
    domain_b = domains.get("domain_b", {})

    for rule in state.get("consolidated_business_rules", []):
        docs.append(
            VectorDocument(
                collection=BUSINESS_RULE,
                key=rule.rule_id,
                text=rule.description or rule.rule_id,
                payload={"rule_id": rule.rule_id, "confidence": rule.confidence},
            )
        )
    for cluster in domain_b.get("capability_clusters", []):
        feature_id = f"feature::{cluster.capability_name}"
        docs.append(
            VectorDocument(
                collection=FEATURE,
                key=feature_id,
                text=cluster.capability_name,
                payload={"feature_id": feature_id, "capability_id": cluster.capability_name},
            )
        )
    for term in domain_b.get("glossary_terms", []):
        docs.append(
            VectorDocument(collection=GLOSSARY, key=term.term, text=term.definition or term.term, payload={"concept_id": term.term})
        )
    for entry in domains.get("domain_d", {}).get("lld", [])[:200]:
        docs.append(
            VectorDocument(
                collection=CODE,
                key=entry.class_or_function,
                text=f"{entry.signature}",
                payload={"method_id": entry.class_or_function, "file_id": entry.file_path},
            )
        )
    inventory = state.get("inventory")
    if inventory is not None:
        for i, readme_path in enumerate(inventory.readme_paths[:5]):
            try:
                content = Path(inventory.abs_path(readme_path)).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            docs.append(VectorDocument(collection=DOC, key=readme_path, text=content[:4000], payload={"file_id": readme_path, "chunk_index": i}))
    return docs


def make_write_vector_index_node(config: PipelineConfig, index_factory=None):
    """Qdrant is candidate-retrieval-only, never authoritative (LLD Section
    14.3) -- so, exactly like every Postgres write in `audit.repository`, a
    Qdrant outage here must never fail the run. The whole body (not just
    client construction) is guarded: an unreachable server only surfaces at
    `write_documents()` time (the client itself connects lazily), not at
    `QdrantVectorIndex(...)` construction.
    """

    def write_vector_index_node(state):
        if not config.qdrant.enabled:
            logger.info("[write_vector_index] QDRANT_ENABLED=false; skipping")
            return {"vector_write_status": {"status": "skipped", "detail": "QDRANT_ENABLED=false"}}
        try:
            index = index_factory() if index_factory else QdrantVectorIndex(config.qdrant.url, config.qdrant.api_key)
            embed_fn = default_embed_fn(config.llm)
            documents = _build_vector_documents(state)
            written = write_documents(index, embed_fn, config.qdrant.collection_prefix, documents)
        except Exception as exc:  # Qdrant is best-effort; it must never fail the run
            logger.warning("[write_vector_index] skipping (Qdrant unavailable): %s", exc, exc_info=True)
            return {"vector_write_status": {"status": "skipped", "detail": str(exc)}}
        logger.info("[write_vector_index] wrote %d document(s)", written)
        return {"vector_write_status": {"status": "written", "detail": f"{written} document(s)"}}

    return write_vector_index_node


# --- N19: write_evidence_store --------------------------------------------


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()[:64]


def _build_evidence_records(state, run_id: str) -> list[EvidenceRecord]:
    records = []
    for claim_id, record in state.get("confidence_scores", {}).items():
        produced_by_node = claim_id.split("::", 1)[0]
        for evidence_ref in record.evidence_ids:
            file_path, _, line_str = evidence_ref.rpartition(":")
            try:
                line = int(line_str)
            except ValueError:
                file_path, line = evidence_ref, None
            records.append(
                EvidenceRecord(
                    evidence_id=_content_hash(file_path or "", str(line), claim_id),
                    source_type="source_code",
                    file_path=file_path or None,
                    line_start=line,
                    line_end=line,
                    produced_by_node=produced_by_node,
                    run_id=run_id,
                )
            )
    return records


def _build_conflict_records(state, run_id: str) -> list[ConflictRecord]:
    resolved_by_claim_id = {r.claim_id: r for r in state.get("resolved_claims", [])}
    records = []
    for conflict in state.get("cross_domain_conflicts", []):
        a, b = conflict.claim_a, conflict.claim_b
        resolution = resolved_by_claim_id.get(a.claim_id)
        status = resolution.status if resolution else "unresolved_written_both"
        resolution_status = "auto_resolved" if status == "disputed_resolved" else "unresolved_written_both"
        policy = "min-confidence-wins-conservative" if resolution_status == "auto_resolved" else "most-evidence-wins"
        records.append(
            ConflictRecord(
                conflict_id=_content_hash(conflict.entity_id, a.claim_id, b.claim_id),
                entity_id=conflict.entity_id,
                claim_a_domain=a.domain,
                claim_a_evidence_id=None,
                claim_a_confidence=a.raw_confidence,
                claim_b_domain=b.domain,
                claim_b_evidence_id=None,
                claim_b_confidence=b.raw_confidence,
                conflict_type=conflict.conflict_type,
                resolution_policy=policy,
                resolution_status=resolution_status,
                run_id=run_id,
            )
        )
    return records


def _build_parse_failures(state, run_id: str) -> list[ParseFailure]:
    inventory = state.get("inventory")
    languages_by_path = {f.path: f.language for f in inventory.files} if inventory else {}
    records = []
    for path, module in state.get("ast_index", {}).items():
        if module is not None:
            continue
        records.append(
            ParseFailure(
                failure_id=_content_hash(path, run_id),
                file_id=path,
                file_path=path,
                language_detected=languages_by_path.get(path),
                parser_attempted=None,
                error_message="parse_failed",
                run_id=run_id,
            )
        )
    return records


def make_write_evidence_store_node(config: PipelineConfig):
    def write_evidence_store_node(state):
        run_id = state.get("run_id", "")
        evidence_records = _build_evidence_records(state, run_id)
        conflict_records = _build_conflict_records(state, run_id)
        parse_failures = _build_parse_failures(state, run_id)
        record_evidence(evidence_records, config.database)
        record_conflicts(conflict_records, config.database)
        record_parse_failures(parse_failures, config.database)
        logger.info(
            "[write_evidence_store] %d evidence record(s), %d conflict record(s), %d parse failure(s)",
            len(evidence_records), len(conflict_records), len(parse_failures),
        )
        return {
            "evidence_write_status": {
                "status": "written",
                "detail": f"{len(evidence_records)} evidence, {len(conflict_records)} conflicts, {len(parse_failures)} parse failures",
            }
        }

    return write_evidence_store_node


# --- N20/N21: loop control + ready_for_query -------------------------------


def route_more_files_pending(state) -> str:
    """Incremental delta re-analysis's selective-domain-skip/bitemporal
    loop-back is a documented follow-up (see the refactor plan's incremental
    scope note) -- this build always finishes in one pass, so this always
    routes to `ready_for_query`. The node/edge exist so the graph topology
    matches LLD Section 4 exactly; the loop condition just never re-enters."""
    return "ready_for_query"


def ready_for_query_node(state):
    return {}

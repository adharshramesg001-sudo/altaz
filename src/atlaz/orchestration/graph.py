"""LangGraph state graph assembly (LLD Section 4's full N1-N21 topology).

`build_state_graph` wires every node this refactor introduces: the
deterministic analysis stage (N1, N4-N9), the capability-registry-gated
domain fan-out (N10/N10ORCH), the cross-domain workflow trace, the
three-tier HITL gate, cross-domain conflict detection and dispute
resolution (N11X-N16), and the three write stages (N17-N19). See
`atlaz.orchestration.nodes`'s module docstring for the two disclosed
scheduling simplifications versus the LLD's literal diagram.

A checkpointer is required whenever `hitl_enabled=True` -- `interrupt()`
has nothing to persist state to otherwise -- so `compile_graph` always
compiles with one (SQLite).
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt as lg_interrupt

from atlaz.llm.client import BaseLLMClient, build_llm_client
from atlaz.orchestration.capability_registry import CapabilityRegistry, load_capability_registry
from atlaz.orchestration.nodes import (
    accept_resolved_node,
    analyze_config_schema_api_node,
    analyze_data_flow_node,
    apply_hitl_resolutions_node,
    auto_resolve_dispute_node,
    build_call_graph_node,
    build_symbol_table_node,
    collect_domain_outputs_node,
    consolidate_business_rules_node,
    detect_cross_domain_conflicts_node,
    make_check_capability_registry_node,
    make_collect_flagged_items_node,
    make_domain_a_node,
    make_domain_b_node,
    make_domain_c_node,
    make_domain_d_node,
    make_domain_orchestrator,
    make_hitl_gate_node,
    make_ingest_repo_node,
    make_write_evidence_store_node,
    make_write_knowledge_graph_node,
    make_write_vector_index_node,
    merge_dependency_graph_node,
    parse_ast_node,
    ready_for_query_node,
    route_after_collect,
    route_and_fan_out_files,
    route_dispute,
    route_more_files_pending,
    score_confidence_node,
    workflow_trace_node,
)
from atlaz.orchestration.serde import build_checkpoint_serializer
from atlaz.orchestration.state import PipelineState
from atlaz.shared.config import PipelineConfig

logger = logging.getLogger(__name__)


def _default_interrupt_fn(flagged):
    return lg_interrupt(flagged)


def build_state_graph(
    config: PipelineConfig,
    llm_client: BaseLLMClient,
    registry: CapabilityRegistry,
    interrupt_fn=_default_interrupt_fn,
    writer_factory=None,
    vector_index_factory=None,
):
    graph = StateGraph(PipelineState)

    # --- N1, N4-N9: ingestion + deterministic analysis ---
    graph.add_node("ingest_repo", make_ingest_repo_node(config))
    graph.add_node("parse_ast", parse_ast_node)
    graph.add_node("build_symbol_table", build_symbol_table_node)
    graph.add_node("build_call_graph", build_call_graph_node)
    graph.add_node("analyze_data_flow", analyze_data_flow_node)
    graph.add_node("analyze_config_schema_api", analyze_config_schema_api_node)
    graph.add_node("merge_dependency_graph", merge_dependency_graph_node)

    # --- N10/N10ORCH: capability registry + domain fan-out ---
    graph.add_node("check_capability_registry", make_check_capability_registry_node(registry))
    graph.add_node("domain_a", make_domain_a_node(registry))
    graph.add_node("domain_b", make_domain_b_node(llm_client, config.confidence_threshold, registry))
    graph.add_node("domain_c", make_domain_c_node(llm_client, registry))
    graph.add_node("domain_d", make_domain_d_node(llm_client, registry))
    graph.add_node("workflow_trace", workflow_trace_node)
    graph.add_node("collect_domain_outputs", collect_domain_outputs_node)

    # --- three-tier HITL gate (gap confirmation / low-confidence finding) ---
    graph.add_node("collect_flagged_items", make_collect_flagged_items_node(config.confidence_threshold))
    graph.add_node("hitl_gate", make_hitl_gate_node(config, interrupt_fn))
    graph.add_node("apply_hitl_resolutions", apply_hitl_resolutions_node)

    # --- N11X-N16: cross-domain conflicts, confidence, dispute resolution ---
    graph.add_node("detect_cross_domain_conflicts", detect_cross_domain_conflicts_node)
    graph.add_node("consolidate_business_rules", consolidate_business_rules_node)
    graph.add_node("score_confidence", score_confidence_node)
    graph.add_node("auto_resolve_dispute", auto_resolve_dispute_node)
    graph.add_node("accept_resolved", accept_resolved_node)

    # --- N17-N19: write stages ---
    graph.add_node("write_knowledge_graph", make_write_knowledge_graph_node(config, writer_factory))
    graph.add_node("write_vector_index", make_write_vector_index_node(config, vector_index_factory))
    graph.add_node("write_evidence_store", make_write_evidence_store_node(config))

    # --- N21 ---
    graph.add_node("ready_for_query", ready_for_query_node)

    graph.add_edge(START, "ingest_repo")
    graph.add_conditional_edges(
        "ingest_repo", route_and_fan_out_files, {"parse_ast": "parse_ast", "build_symbol_table": "build_symbol_table"}
    )
    graph.add_edge("parse_ast", "build_symbol_table")
    graph.add_edge("build_symbol_table", "build_call_graph")
    graph.add_edge("build_symbol_table", "analyze_data_flow")
    graph.add_edge("build_symbol_table", "analyze_config_schema_api")
    graph.add_edge("build_call_graph", "merge_dependency_graph")
    graph.add_edge("analyze_data_flow", "merge_dependency_graph")
    graph.add_edge("analyze_config_schema_api", "merge_dependency_graph")
    graph.add_edge("merge_dependency_graph", "check_capability_registry")
    graph.add_conditional_edges(
        "check_capability_registry",
        make_domain_orchestrator(registry),
        {"domain_a": "domain_a", "domain_b": "domain_b", "domain_c": "domain_c", "domain_d": "domain_d", "workflow_trace": "workflow_trace"},
    )
    graph.add_edge("domain_a", "workflow_trace")
    graph.add_edge("domain_b", "workflow_trace")
    graph.add_edge("domain_c", "workflow_trace")
    graph.add_edge("domain_d", "workflow_trace")
    graph.add_edge("workflow_trace", "collect_domain_outputs")
    graph.add_edge("collect_domain_outputs", "collect_flagged_items")
    graph.add_conditional_edges(
        "collect_flagged_items", route_after_collect, {"hitl_gate": "hitl_gate", "apply_hitl_resolutions": "apply_hitl_resolutions"}
    )
    graph.add_edge("hitl_gate", "apply_hitl_resolutions")
    graph.add_edge("apply_hitl_resolutions", "detect_cross_domain_conflicts")
    graph.add_edge("detect_cross_domain_conflicts", "consolidate_business_rules")
    graph.add_edge("consolidate_business_rules", "score_confidence")
    graph.add_conditional_edges(
        "score_confidence", route_dispute, {"auto_resolve_dispute": "auto_resolve_dispute", "accept_resolved": "accept_resolved"}
    )
    graph.add_edge("auto_resolve_dispute", "accept_resolved")
    graph.add_edge("accept_resolved", "write_knowledge_graph")
    graph.add_edge("write_knowledge_graph", "write_vector_index")
    graph.add_edge("write_vector_index", "write_evidence_store")
    graph.add_conditional_edges("write_evidence_store", route_more_files_pending, {"ready_for_query": "ready_for_query"})
    graph.add_edge("ready_for_query", END)

    return graph


def compile_graph(
    config: PipelineConfig,
    llm_client: BaseLLMClient | None = None,
    writer_factory=None,
    vector_index_factory=None,
    registry: CapabilityRegistry | None = None,
):
    if llm_client is None:
        logger.info("Building LLM client: provider=%s model=%s", config.llm.provider, config.llm.model)
        llm_client = build_llm_client(config.llm)
    if registry is None:
        registry = load_capability_registry(config.capability_registry_path)

    graph = build_state_graph(
        config, llm_client, registry, writer_factory=writer_factory, vector_index_factory=vector_index_factory
    )

    checkpoint_path = Path(config.checkpoint_db_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Compiling pipeline graph: checkpoint_db=%s hitl_enabled=%s", checkpoint_path, config.hitl_enabled)
    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn, serde=build_checkpoint_serializer())

    return graph.compile(checkpointer=checkpointer)

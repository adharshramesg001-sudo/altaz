"""LangGraph state graph assembly (LLD Section 9).

`build_graph` is the "orchestrator" the HLD refers to throughout: it wires
every domain agent, the merge/collect step, the single consolidated HITL
gate, and the Neo4j write into one compiled, checkpointed graph. A
checkpointer is required whenever `hitl_enabled=True` -- `interrupt()` has
nothing to persist state to otherwise -- so `run_pipeline` always compiles
with one (SQLite, per LLD Section 13.1's "config-gated: Streamlit form when
hitl_enabled=true").
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt as lg_interrupt

from atlaz.llm.client import BaseLLMClient, build_llm_client
from atlaz.orchestration.nodes import (
    make_collect_node,
    make_domain_a_node,
    make_domain_b_node,
    make_domain_c_node,
    make_domain_d_node,
    make_graph_write_node,
    make_hitl_gate_node,
    make_ingest_node,
    make_parse_node,
    make_prepare_graph_batch_node,
    route_after_collect,
)
from atlaz.orchestration.serde import build_checkpoint_serializer
from atlaz.orchestration.state import PipelineState
from atlaz.shared.config import PipelineConfig


def _default_interrupt_fn(flagged):
    return lg_interrupt(flagged)


def build_state_graph(
    config: PipelineConfig, llm_client: BaseLLMClient, interrupt_fn=_default_interrupt_fn, writer_factory=None
):
    graph = StateGraph(PipelineState)

    graph.add_node("ingest", make_ingest_node(config))
    graph.add_node("parse", make_parse_node())
    graph.add_node("domain_c", make_domain_c_node(llm_client))
    graph.add_node("domain_d", make_domain_d_node(llm_client))
    graph.add_node("domain_b", make_domain_b_node(llm_client, config.confidence_threshold))
    graph.add_node("domain_a", make_domain_a_node())
    graph.add_node("collect", make_collect_node(config.confidence_threshold))
    graph.add_node("hitl_gate", make_hitl_gate_node(config, interrupt_fn))
    graph.add_node("prepare_graph_batch", make_prepare_graph_batch_node(config.confidence_threshold))
    graph.add_node("graph_write", make_graph_write_node(config, writer_factory))

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "parse")
    graph.add_edge("parse", "domain_c")
    graph.add_edge("domain_c", "domain_d")
    graph.add_edge("domain_d", "domain_b")
    graph.add_edge("domain_b", "domain_a")
    graph.add_edge("domain_a", "collect")
    graph.add_conditional_edges(
        "collect", route_after_collect, {"hitl_gate": "hitl_gate", "prepare_graph_batch": "prepare_graph_batch"}
    )
    graph.add_edge("hitl_gate", "prepare_graph_batch")
    graph.add_edge("prepare_graph_batch", "graph_write")
    graph.add_edge("graph_write", END)

    return graph


def compile_graph(config: PipelineConfig, llm_client: BaseLLMClient | None = None, writer_factory=None):
    llm_client = llm_client or build_llm_client(config.llm)
    graph = build_state_graph(config, llm_client, writer_factory=writer_factory)

    checkpoint_path = Path(config.checkpoint_db_path)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn, serde=build_checkpoint_serializer())

    return graph.compile(checkpointer=checkpointer)

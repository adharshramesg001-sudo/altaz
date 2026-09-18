#!/usr/bin/env python3
"""Runnable trace of AtlaZ's ingestion pipeline -- prints every node in the
LangGraph state graph as it fires, and exactly which `PipelineState` keys
it added or changed. This is a *reading aid*, not a pytest test: run it
directly and watch the state grow, node by node, to see how a data point
(a file on disk) becomes AST -> symbols -> domain findings -> a graph
write batch.

The repo it ingests defaults to `DEFAULT_REPO_PATH` (set just below the
imports) -- edit that constant to point at whatever you're currently
debugging, or override per-run with --repo. --sample ignores both and uses
a tiny built-in 2-file sample instead.

Two modes:

  - Default (no --real): fully offline. No Neo4j, Qdrant, Postgres, or LLM
    API key needed. Uses `MockLLMClient` and fake Neo4j/Qdrant writers that
    just record what *would* have been written (same pattern as
    `tests/unit/orchestration/test_graph_end_to_end.py`).

  - --real: the genuine end-to-end pipeline against your real repo and
    real infrastructure. Reads `.env` (LLM_PROVIDER, NEO4J_*, DATABASE_URL,
    QDRANT_*), makes real LLM calls, writes real nodes/edges into your real
    Neo4j, and records a real row in the Postgres audit trail -- so the run
    it produces is immediately usable from `atlaz app` (Retrieve & Document
    / Modernize) or `atlaz ask` afterward, exactly like a normal `atlaz
    run`. Not allowed with --sample. This is real, not reversible without
    manually cleaning up the graph -- it writes into the same Neo4j/
    Postgres your other AtlaZ work uses, same as `atlaz run` would.

Where to look next while reading the output:
  - `src/atlaz/orchestration/graph.py`  -- the node/edge wiring this
    script is walking (the comment blocks group nodes into LLD stages;
    this script prints those same group labels next to each node).
  - `src/atlaz/orchestration/state.py`  -- `PipelineState`, the TypedDict
    every key below is a field of.
  - `src/atlaz/orchestration/nodes.py`  -- what each node actually does.

Usage:
    python scripts/trace_pipeline_flow.py                  # DEFAULT_REPO_PATH below, mocked
    python scripts/trace_pipeline_flow.py --real            # DEFAULT_REPO_PATH below, real infra
    python scripts/trace_pipeline_flow.py --sample          # tiny built-in sample repo instead
    python scripts/trace_pipeline_flow.py --repo /path/to/a/repo
    python scripts/trace_pipeline_flow.py --repo /path/to/a/repo --real
    python scripts/trace_pipeline_flow.py --repo /path/to/a/repo --real --hitl --thread-id my-run-1
"""

from __future__ import annotations

import argparse
import dataclasses
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# Edit this to whatever repo you're currently debugging -- it's the default
# target for both plain runs and --real runs, so you don't have to retype
# --repo every time. Overridden by --repo on the command line; ignored
# entirely if --sample is given.
DEFAULT_REPO_PATH = "/home/adharsh.ramesh@zucisystems.com/Downloads/fastapi-microservices/inference-service"

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from atlaz.audit.repository import record_resolutions, record_run_started, record_run_status
from atlaz.graph_store.schema import NodeLabel
from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.llm.client import MockLLMClient, build_llm_client
from atlaz.orchestration.capability_registry import load_capability_registry, to_snapshot
from atlaz.orchestration.graph import build_state_graph
from atlaz.orchestration.serde import build_checkpoint_serializer
from atlaz.shared.config import DatabaseConfig, Neo4jConfig, PipelineConfig

# ---------------------------------------------------------------------------
# Built-in sample repo -- used only when --repo isn't given. Big enough
# that every domain (A: gap detection, B: business rules, C: FRD
# extraction, D: HLD/LLD) has something real to find, small enough to read
# the whole trace in one go.
# ---------------------------------------------------------------------------

_SAMPLE_MODULE = '''
"""Order billing module."""


class BillingPlan:
    late_fee_rate: float = 0.045


def compute_late_fee(order_id: int) -> float:
    """Computes the late fee for an order."""
    return BillingPlan.late_fee_rate * 100
'''

_SAMPLE_TEST = """
from billing import compute_late_fee


def test_compute_late_fee_is_positive():
    assert compute_late_fee(1) > 0
"""

_SAMPLE_README = "This tool exists to help finance teams because manual billing was error-prone."


def _write_sample_repo(root: Path) -> str:
    (root / "billing.py").write_text(_SAMPLE_MODULE)
    (root / "test_billing.py").write_text(_SAMPLE_TEST)
    (root / "README.md").write_text(_SAMPLE_README)
    return str(root)


# ---------------------------------------------------------------------------
# Fakes for the offline default mode -- same shape as the ones in
# test_graph_end_to_end.py. Not used at all when --real is given: leaving
# writer_factory/vector_index_factory as None makes the pipeline's own node
# factories fall back to the real Neo4jWriter/QdrantVectorIndex (see
# `make_write_knowledge_graph_node`/`make_write_vector_index_node` in
# orchestration/nodes.py).
# ---------------------------------------------------------------------------


class FakeWriter:
    def ensure_schema(self) -> None:
        pass

    def write_batch(self, nodes, edges, repo_id=None) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass


class FakeVectorIndex:
    def ensure_collection(self, collection, dimension) -> None:
        pass

    def upsert(self, collection, point_id, vector, payload) -> None:
        pass

    def search(self, collection, vector, limit):
        return []


# ---------------------------------------------------------------------------
# Node -> LLD stage-group label, copied verbatim from the comment blocks in
# orchestration/graph.py so this trace reads side-by-side with that file.
# ---------------------------------------------------------------------------

_STAGE_LABELS: dict[str, str] = {
    "ingest_repo": "N1, N4-N9: ingestion + deterministic analysis",
    "parse_ast": "N1, N4-N9: ingestion + deterministic analysis",
    "build_symbol_table": "N1, N4-N9: ingestion + deterministic analysis",
    "build_call_graph": "N1, N4-N9: ingestion + deterministic analysis",
    "analyze_data_flow": "N1, N4-N9: ingestion + deterministic analysis",
    "analyze_config_schema_api": "N1, N4-N9: ingestion + deterministic analysis",
    "merge_dependency_graph": "N1, N4-N9: ingestion + deterministic analysis",
    "check_capability_registry": "N10/N10ORCH: capability registry + domain fan-out",
    "domain_a": "N10/N10ORCH: capability registry + domain fan-out (parallel)",
    "domain_b": "N10/N10ORCH: capability registry + domain fan-out (parallel)",
    "domain_c": "N10/N10ORCH: capability registry + domain fan-out (parallel)",
    "domain_d": "N10/N10ORCH: capability registry + domain fan-out (parallel)",
    "workflow_trace": "N10/N10ORCH: cross-domain (B+D) workflow trace, fan-in",
    "collect_domain_outputs": "N10/N10ORCH: fan-in",
    "collect_flagged_items": "three-tier HITL gate",
    "hitl_gate": "three-tier HITL gate",
    "apply_hitl_resolutions": "three-tier HITL gate",
    "detect_cross_domain_conflicts": "N11X-N16: cross-domain conflicts, confidence, dispute resolution",
    "consolidate_business_rules": "N11X-N16: cross-domain conflicts, confidence, dispute resolution",
    "score_confidence": "N11X-N16: cross-domain conflicts, confidence, dispute resolution",
    "auto_resolve_dispute": "N11X-N16: cross-domain conflicts, confidence, dispute resolution",
    "accept_resolved": "N11X-N16: cross-domain conflicts, confidence, dispute resolution",
    "write_knowledge_graph": "N17-N19: write stages",
    "write_vector_index": "N17-N19: write stages",
    "write_evidence_store": "N17-N19: write stages",
    "ready_for_query": "N21: terminal",
}


# ---------------------------------------------------------------------------
# Pretty-printing the state diff at each step -- this is the actual "how
# does a data point flow" payoff.
# ---------------------------------------------------------------------------


def _short_repr(value: Any, max_len: int = 90) -> str:
    text = repr(value)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _preview(value: Any, max_len: int = 90) -> str:
    if isinstance(value, list):
        if not value:
            return "[] (empty)"
        return f"list[{len(value)}] e.g. {_short_repr(value[0], max_len)}"
    if isinstance(value, dict):
        if not value:
            return "{} (empty)"
        keys = ", ".join(str(k) for k in list(value)[:5])
        more = "…" if len(value) > 5 else ""
        return f"dict[{len(value)}] keys: {keys}{more}"
    return _short_repr(value, max_len)


def _preview_domains(domains_partial: dict) -> str:
    """`domains` is namespaced per domain (see state.py's `DomainState`) --
    unwrap one level so the domain name shows up next to its own output,
    instead of a flat 'dict[1] keys: domain_c'."""
    parts = []
    for domain_name, output in domains_partial.items():
        if not isinstance(output, dict):
            parts.append(f"{domain_name}={_short_repr(output)}")
            continue
        sub = ", ".join(f"{k}={_preview(v, 50)}" for k, v in output.items()) or "(no fields set)"
        parts.append(f"{domain_name}: {sub}")
    return " | ".join(parts)


def _print_step(step_num: int, node_name: str, update: dict) -> None:
    stage = _STAGE_LABELS.get(node_name, "?")
    print(f"\n[{step_num:>2}] {node_name}  —  {stage}")
    for key, value in update.items():
        line = _preview_domains(value) if key == "domains" and isinstance(value, dict) else _preview(value)
        print(f"     state.{key}  ->  {line}")


def _print_interrupt(flagged: list) -> None:
    print("\n[ ⏸ ] hitl_gate  —  three-tier HITL gate")
    print(f"     PAUSED: {len(flagged)} item(s) flagged for review, e.g.:")
    for item in flagged[:3]:
        print(f"       - {item.kind.value}: {_short_repr(getattr(item, 'summary', item), 90)}")


# ---------------------------------------------------------------------------
# Real-service connectivity checks -- same checks as
# tests/integration/conftest.py's require_neo4j/require_database fixtures,
# but a hard failure here instead of a pytest skip: --real is only worth
# running when the services it's about to write into are actually up.
# Qdrant is deliberately NOT checked here -- write_vector_index_node
# already treats it as best-effort and degrades to "skipped" on its own.
# ---------------------------------------------------------------------------


def _check_neo4j(neo4j_config: Neo4jConfig) -> None:
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable

    driver = GraphDatabase.driver(neo4j_config.uri, auth=(neo4j_config.user, neo4j_config.password))
    try:
        driver.verify_connectivity()
    except ServiceUnavailable as exc:
        raise SystemExit(f"--real: Neo4j is not reachable at {neo4j_config.uri}: {exc}") from exc
    finally:
        driver.close()


def _check_database(database_config: DatabaseConfig) -> None:
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    engine = create_engine(database_config.url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        raise SystemExit(
            f"--real: Postgres audit database is not reachable at {database_config.url}: {exc}\n"
            "Run `atlaz db init` first."
        ) from exc
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def _build_app(config: PipelineConfig, llm_client, real: bool):
    registry = load_capability_registry()
    graph = build_state_graph(
        config,
        llm_client,
        registry,
        writer_factory=None if real else (lambda: FakeWriter()),
        vector_index_factory=None if real else (lambda: FakeVectorIndex()),
    )
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    return graph.compile(checkpointer=SqliteSaver(conn, serde=build_checkpoint_serializer())), registry


def _print_summary(final_state: dict, real: bool, thread_id: str, repo_id: str) -> None:
    nodes = final_state.get("graph_write_nodes", [])
    edges = final_state.get("graph_write_edges", [])
    counts: dict[NodeLabel, int] = {}
    for node in nodes:
        counts[node.label] = counts.get(node.label, 0) + 1

    print("\n" + "=" * 72)
    label = "Real graph write batch (written to your real Neo4j):" if real else "Final graph write batch (what write_knowledge_graph would send to Neo4j):"
    print(label)
    print(f"  {len(nodes)} nodes, {len(edges)} edges")
    for gnode_label, count in sorted(counts.items(), key=lambda kv: kv[0].value):
        print(f"    {gnode_label.value:<24} {count}")

    for status_key, service in (
        ("kg_write_status", "Neo4j"),
        ("vector_write_status", "Qdrant"),
        ("evidence_write_status", "Postgres evidence store"),
    ):
        status = final_state.get(status_key)
        if status:
            print(f"  {service}: {status.get('status')} -- {status.get('detail')}")

    if real:
        print(f"\nthread_id: {thread_id}")
        print(f"This is now a real completed run for project '{repo_id}' -- try:")
        print(f'  atlaz ask {thread_id} "What does this project do?"')
        print(f"  atlaz document {thread_id} {repo_id}")
        print("  ...or open `atlaz app` and pick this project under Retrieve & Document / Modernize.")


def run_trace(
    repo_path: str | None,
    real: bool,
    hitl_enabled: bool,
    thread_id: str | None,
) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        if repo_path is None:
            repo_path = _write_sample_repo(Path(tmp))
        else:
            repo_path = str(Path(repo_path).expanduser().resolve())
            if not Path(repo_path).is_dir():
                raise SystemExit(f"--repo {repo_path!r} is not a directory")

        if real:
            config = dataclasses.replace(PipelineConfig.from_env(), hitl_enabled=hitl_enabled)
            _check_neo4j(config.neo4j)
            _check_database(config.database)
            llm_client = build_llm_client(config.llm)
        else:
            config = PipelineConfig(hitl_enabled=hitl_enabled, confidence_threshold=0.6)
            llm_client = MockLLMClient()

        app, registry = _build_app(config, llm_client, real)

        thread_id = thread_id or str(uuid.uuid4())
        run_config = {"configurable": {"thread_id": thread_id}}
        repo_id = Path(repo_path).name
        initial_state = {"run_id": thread_id, "repo_path": repo_path, "run_mode": "full", "changed_files": None}

        print("=" * 72)
        print(f"Tracing {'REAL' if real else 'mocked'} run_pipeline() over {repo_path}")
        print(f"hitl_enabled={hitl_enabled}  thread_id={thread_id}  (each [step] is one LangGraph node firing)")
        if real:
            print(f"llm_provider={config.llm.provider}  neo4j={config.neo4j.uri}  database={config.database.url}")
        print("=" * 72)

        if real:
            record_run_started(
                thread_id, repo_path, config.hitl_enabled, config.database,
                repo_id=repo_id, run_mode="full", capability_registry_snapshot=to_snapshot(registry),
            )

        try:
            step = 0
            for chunk in app.stream(initial_state, config=run_config, stream_mode="updates"):
                for node_name, update in chunk.items():
                    step += 1
                    if node_name == "__interrupt__":
                        _print_interrupt(update[0].value if isinstance(update, tuple | list) else update)
                        continue
                    _print_step(step, node_name, update or {})

            if hitl_enabled:
                flagged = app.get_state(run_config).values.get("flagged_for_review", [])
                resolutions = auto_resolve(flagged)
                print(f"\n>>> Resuming with {len(resolutions)} auto-resolution(s) (this is what a human reviewer's")
                print("    submitted decisions would otherwise produce) via resume_pipeline()/Command(resume=...):")
                for chunk in app.stream(Command(resume=resolutions), config=run_config, stream_mode="updates"):
                    for node_name, update in chunk.items():
                        step += 1
                        _print_step(step, node_name, update or {})

            final_state = app.get_state(run_config).values
        except Exception as exc:
            if real:
                record_run_status(thread_id, "failed", error=str(exc), config=config.database)
            raise

        if real:
            resolutions_to_record = final_state.get("hitl_resolutions") or []
            if resolutions_to_record:
                record_resolutions(thread_id, resolutions_to_record, config.database)
            record_run_status(
                thread_id, "complete",
                nodes_written=len(final_state.get("graph_write_nodes", [])),
                edges_written=len(final_state.get("graph_write_edges", [])),
                config=config.database,
            )

        _print_summary(final_state, real, thread_id, repo_id)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo",
        metavar="PATH",
        default=DEFAULT_REPO_PATH,
        help=f"Repository to ingest. Defaults to DEFAULT_REPO_PATH at the top of this file "
        f"(currently {DEFAULT_REPO_PATH!r}) -- edit that constant to change what 'no --repo' means.",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="Ignore --repo/DEFAULT_REPO_PATH and use the tiny built-in 2-file sample repo instead "
        "-- the offline, no-setup way to read the trace.",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use real Neo4j/Qdrant/Postgres/LLM from .env instead of mocks/fakes. Writes real data. "
        "Not allowed with --sample.",
    )
    parser.add_argument(
        "--hitl",
        action="store_true",
        help="Run with hitl_enabled=True to also show the pause-at-hitl_gate / resume path "
        "(default runs with HITL disabled -- the same mode the webapp's Ingest page uses).",
    )
    parser.add_argument(
        "--thread-id",
        metavar="ID",
        help="Use this thread_id instead of a random one (useful with --real, to pick a memorable "
        "id you can pass to `atlaz ask`/`atlaz document` afterward).",
    )
    args = parser.parse_args()

    if args.real and args.sample:
        parser.error("--real and --sample don't mix -- --real makes real LLM calls and writes real "
                     "graph data, which isn't worth doing against the throwaway sample repo.")

    repo_path = None if args.sample else args.repo
    run_trace(repo_path=repo_path, real=args.real, hitl_enabled=args.hitl, thread_id=args.thread_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

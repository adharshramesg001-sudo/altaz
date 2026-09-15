"""CLI entry point (`atlaz` console script, per pyproject.toml).

Commands:
  atlaz run <repo_path> [--thread-id ID]
      Ingests and extracts knowledge from a repository. If HITL is enabled
      and something was flagged, the run pauses and prints the thread id
      needed to review it.
  atlaz review <thread_id>
      Launches the Streamlit review app pointed at a specific paused run.
  atlaz resume <thread_id>
      Applies the auto-resolve policy and finishes a paused run without a
      human reviewer (equivalent to what happens automatically when
      HITL_ENABLED=false) -- useful for CI or a hands-off demo.
  atlaz ask <thread_id> "<question>" [--mode qa|enhancement|modernization|drift|product_synthesis]
      Runs one reasoning-layer query against the knowledge graph.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.llm.client import build_llm_client
from atlaz.orchestration.runner import resume_pipeline, run_pipeline
from atlaz.reasoning.neo4j_query_runner import Neo4jReasoningStore
from atlaz.reasoning.reasoning_agent import ReasoningAgent, ReasoningMode
from atlaz.shared.config import PipelineConfig


def _cmd_run(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_env()
    result = run_pipeline(args.repo_path, config, thread_id=args.thread_id)

    if result.status == "pending_review":
        print(f"Run paused for human review. thread_id = {result.thread_id}")
        print(f"  Flagged items: {len(result.pending_items or [])}")
        print(f"  Review with:  atlaz review {result.thread_id}")
        print(f"  Or auto-resolve without a reviewer:  atlaz resume {result.thread_id}")
        return 0

    print(f"Run complete. thread_id = {result.thread_id}")
    print(f"  Nodes written: {len(result.state.get('graph_write_nodes', []))}")
    print(f"  Edges written: {len(result.state.get('graph_write_edges', []))}")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_env()
    from atlaz.orchestration.runner import get_pending_review_items

    flagged = get_pending_review_items(args.thread_id, config)
    if not flagged:
        print(f"No pending review items for thread_id={args.thread_id} (already resolved, or unknown thread).")
        return 1

    resolutions = auto_resolve(flagged)
    result = resume_pipeline(args.thread_id, resolutions, config)
    print(f"Run complete via auto-resolve. thread_id = {result.thread_id}")
    print(f"  Nodes written: {len(result.state.get('graph_write_nodes', []))}")
    print(f"  Edges written: {len(result.state.get('graph_write_edges', []))}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    app_path = Path(__file__).parent / "hitl" / "streamlit_app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path), "--", "--thread-id", args.thread_id]
    return subprocess.call(cmd)


def _cmd_ask(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_env()
    llm_client = build_llm_client(config.llm)
    with Neo4jReasoningStore(config.neo4j) as store:
        agent = ReasoningAgent(llm_client, store.run)
        result = agent.answer(args.question, ReasoningMode(args.mode))

    print(result.answer_text)
    print(f"\nconfidence: {result.confidence:.2f}")
    if result.cited_nodes:
        print(f"cited: {', '.join(result.cited_nodes)}")
    if result.gaps_encountered:
        print("gaps encountered:")
        for gap in result.gaps_encountered:
            print(f"  - {gap}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlaz", description="AtlaZ codebase knowledge extraction framework")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the extraction pipeline against a repository")
    run_parser.add_argument("repo_path")
    run_parser.add_argument("--thread-id", default=None)
    run_parser.set_defaults(func=_cmd_run)

    resume_parser = subparsers.add_parser("resume", help="Auto-resolve a paused run and finish it")
    resume_parser.add_argument("thread_id")
    resume_parser.set_defaults(func=_cmd_resume)

    review_parser = subparsers.add_parser("review", help="Launch the Streamlit HITL review app for a paused run")
    review_parser.add_argument("thread_id")
    review_parser.set_defaults(func=_cmd_review)

    ask_parser = subparsers.add_parser("ask", help="Ask the reasoning layer a question")
    ask_parser.add_argument("question")
    ask_parser.add_argument(
        "--mode", default="qa", choices=[m.value for m in ReasoningMode]
    )
    ask_parser.set_defaults(func=_cmd_ask)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

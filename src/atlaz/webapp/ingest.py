"""Ingest page -- the only way a repository enters AtlaZ in this app.

Accepts a local filesystem path or a git URL (shallow-cloned into
`.atlaz/workspaces/`, see `atlaz.ingestion.git_source`). Runs the full
ingestion pipeline synchronously, in-process (no Celery/API required to use
this app) with the three-tier HITL gate forced off -- any low-confidence
finding or the business-case gap is auto-resolved inline and written to the
graph, correctly labeled, rather than pausing for a review screen this app
doesn't have. Nothing here is user-configurable: LLM provider, Neo4j/
Qdrant/Postgres connection, and confidence threshold all come from `.env`.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import streamlit as st

from atlaz.graph_store.schema import NodeLabel
from atlaz.ingestion.git_source import GitCloneError, is_git_source, resolve_repo_source
from atlaz.orchestration.runner import PipelineRunResult, run_pipeline
from atlaz.shared.config import PipelineConfig
from atlaz.webapp import style

_WORKSPACE_ROOT = Path(".atlaz/workspaces")

_SUMMARY_LABELS = [
    ("Capabilities", NodeLabel.BUSINESS_CAPABILITY, "good"),
    ("Business rules", NodeLabel.BUSINESS_RULE, ""),
    ("Classes", NodeLabel.CLASS, ""),
    ("Methods", NodeLabel.METHOD, ""),
]


def render() -> None:
    style.page_heading(
        "📥 Ingest a repository",
        "STEP 1",
        "Point AtlaZ at a local folder or a git repository URL. It reads the code and builds an "
        "evidence-grounded knowledge graph -- once it's done, use **Retrieve & Document** to ask "
        "questions or generate design docs.",
    )

    source = st.text_input(
        "Repository path or git URL",
        placeholder="/path/to/repo   or   https://github.com/org/repo.git",
        key="ingest_source",
    )
    st.caption("Runs fully automatically -- anything low-confidence is written to the graph, flagged for reference, never blocked on approval.")

    if st.button("Start ingestion", type="primary", disabled=not source.strip()):
        _run_ingestion(source)

    result: PipelineRunResult | None = st.session_state.get("last_ingest_result")
    if result:
        st.divider()
        _render_result(result)


def _run_ingestion(source: str) -> None:
    config = dataclasses.replace(PipelineConfig.from_env(), hitl_enabled=False)

    try:
        with st.spinner("Cloning repository..." if is_git_source(source) else "Reading repository..."):
            local_path = resolve_repo_source(source, _WORKSPACE_ROOT)
    except (GitCloneError, ValueError) as exc:
        st.error(str(exc))
        return

    try:
        with st.spinner("Analyzing the codebase — this can take a minute or two..."):
            result = run_pipeline(local_path, config)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        st.error(f"Ingestion failed: {exc}")
        return

    st.session_state["last_ingest_result"] = result
    st.session_state["selected_thread_id"] = result.thread_id
    st.rerun()


def _render_result(result: PipelineRunResult) -> None:
    if result.status != "complete":
        st.warning(f"Run ended with status: {result.status}")  # shouldn't happen with hitl_enabled=False
        return

    nodes = result.state.get("graph_write_nodes", [])
    edges = result.state.get("graph_write_edges", [])
    counts: dict[NodeLabel, int] = {}
    for n in nodes:
        counts[n.label] = counts.get(n.label, 0) + 1

    repo_meta = result.state.get("repo_meta")

    st.success(f"✅ Ingestion complete for **{repo_meta.name if repo_meta else result.thread_id}**")
    if repo_meta and repo_meta.primary_languages:
        style.chips(repo_meta.primary_languages)

    columns = st.columns(len(_SUMMARY_LABELS) + 2)
    style.stat_card(columns[0], len(nodes), "Graph nodes", "good")
    style.stat_card(columns[1], len(edges), "Relationships", "good")
    for column, (title, label, tone) in zip(columns[2:], _SUMMARY_LABELS, strict=True):
        style.stat_card(column, counts.get(label, 0), title, tone)

    st.info("Head to **Retrieve & Document** in the sidebar to ask questions or generate design docs for this project.")


if __name__ == "__main__":
    st.set_page_config(page_title="AtlaZ — Ingest", page_icon="📥", layout="wide")
    style.inject()
    render()

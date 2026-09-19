"""AtlaZ Streamlit app entry point -- three tabs plus a sidebar project
picker:

- Ingest: point AtlaZ at a repo (local path or git URL); runs the full
  ingestion pipeline in-process, HITL auto-resolved inline (no separate
  review screen).
- Retrieve & Document: ask questions against an ingested project's
  knowledge graph, review inferred cross-repo links, and generate/download
  its HLD and LLD.
- Modernize: describe a change in plain English; AtlaZ drafts a
  modernization plan and code grounded in the knowledge graph, validates
  it, and lets you review/download the proposal -- never writes back into
  the ingested repo.

Retrieve & Document and Modernize both operate on whichever project is
picked in the sidebar (see `_render_sidebar()`) -- one picker, always
visible, rather than a widget duplicated in (or a dedicated tab shared by)
each of the two tabs that need it.

No configuration is exposed in this app -- LLM provider, Neo4j/Qdrant/
Postgres connection, and confidence threshold all come from `.env`,
silently, in every tab.

Run via `atlaz app` (wraps `streamlit run main.py`), or directly:
    streamlit run src/atlaz/webapp/main.py
"""

from __future__ import annotations

from typing import Callable

import streamlit as st

from atlaz.audit.models import PipelineRun
from atlaz.audit.repository import list_completed_runs
from atlaz.webapp import ingest, modernize, retrieve, style
from atlaz.webapp.project_picker import select_project

_TAB_TITLES = ["📥 Ingest", "🔎 Retrieve & Document", "🛠️ Modernize"]


def main() -> None:
    st.set_page_config(page_title="AtlaZ", page_icon="🧭", layout="wide")
    style.inject()

    runs, runs_error = _load_runs()
    active_run = _render_sidebar(runs, runs_error)

    style.hero(
        "🧭 AtlaZ",
        "Ingest a repository, then ask questions, generate design docs, and draft modernizations -- "
        "all grounded in an evidence-backed knowledge graph.",
        badges=["1 · Ingest", "2 · Retrieve & Document", "3 · Modernize"],
    )

    tab_ingest, tab_retrieve, tab_modernize = st.tabs(_TAB_TITLES)

    with tab_ingest, st.container(key="band-ingest"):
        ingest.render()

    with tab_retrieve, st.container(key="band-retrieve"):
        _render_downstream_tab(runs_error, active_run, retrieve.render_body)

    with tab_modernize, st.container(key="band-modernize"):
        _render_downstream_tab(runs_error, active_run, modernize.render_body)


def _load_runs() -> tuple[list[PipelineRun], Exception | None]:
    try:
        return list_completed_runs(), None
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        return [], exc


def _render_downstream_tab(
    runs_error: Exception | None,
    active_run: PipelineRun | None,
    render_body: Callable[[PipelineRun], None],
) -> None:
    if runs_error:
        st.error(f"Couldn't reach the audit database: {runs_error}")
        return
    if active_run is None:
        st.info("No ingested projects yet. Use **📥 Ingest** to get started, then pick it from the sidebar.")
        return
    render_body(active_run)


def _render_sidebar(runs: list[PipelineRun], runs_error: Exception | None) -> PipelineRun | None:
    with st.sidebar:
        st.markdown("## 🧭 AtlaZ")
        st.caption("Codebase knowledge, grounded in evidence.")
        st.divider()
        st.caption("📥 Ingest  →  🔎 Retrieve & Document  →  🛠️ Modernize")
        st.divider()

        if runs_error:
            st.error("Couldn't load projects.")
            return None
        if not runs:
            st.caption("No ingested projects yet -- use **Ingest** to get started.")
            return None
        return select_project(runs)


if __name__ == "__main__":
    main()

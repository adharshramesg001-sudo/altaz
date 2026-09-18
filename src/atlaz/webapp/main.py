"""AtlaZ Streamlit app entry point -- a single scrolling page, three
sections, top to bottom:

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

Retrieve & Document and Modernize share one project picker, shown once
right below Ingest, so picking a project carries through both sections
below it (see `retrieve.render_body()` / `modernize.render_body()`).

No configuration is exposed in this app -- LLM provider, Neo4j/Qdrant/
Postgres connection, and confidence threshold all come from `.env`,
silently, in every section.

Run via `atlaz app` (wraps `streamlit run main.py`), or directly:
    streamlit run src/atlaz/webapp/main.py
"""

from __future__ import annotations

import streamlit as st

from atlaz.audit.repository import list_completed_runs
from atlaz.webapp import ingest, modernize, retrieve, style
from atlaz.webapp.project_picker import select_project

_NAV_ITEMS = [
    ("📥 Ingest", "ingest"),
    ("📂 Project", "project"),
    ("🔎 Retrieve & Document", "retrieve"),
    ("🛠️ Modernize", "modernize"),
]


def main() -> None:
    st.set_page_config(page_title="AtlaZ", page_icon="🧭", layout="wide")
    style.inject()
    _render_sidebar()

    style.hero(
        "🧭 AtlaZ",
        "Ingest a repository, then ask questions, generate design docs, and draft modernizations -- "
        "all grounded in an evidence-backed knowledge graph, one page top to bottom.",
        badges=["1 · Ingest", "2 · Retrieve & Document", "3 · Modernize"],
    )

    with st.container(key="band-ingest"):
        ingest.render()
    style.section_divider()
    _render_project_and_below()


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown("## 🧭 AtlaZ")
        st.caption("Codebase knowledge, grounded in evidence.")
        st.divider()
        style.sidebar_nav(_NAV_ITEMS)

        active_repo_id = st.session_state.get("selected_thread_id")
        if active_repo_id:
            st.divider()
            st.caption("Active project")
            st.markdown(f"`{active_repo_id}`")


def _render_project_and_below() -> None:
    try:
        runs = list_completed_runs()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        style.anchor("project")
        st.error(f"Couldn't reach the audit database: {exc}")
        return

    style.anchor("project")
    if not runs:
        st.info(
            "No ingested projects yet. Use **Ingest** above to get started -- **Retrieve & Document** "
            "and **Modernize** will appear here once a run completes."
        )
        return

    with st.container(key="band-project", border=True):
        st.markdown("#### 📂 Project")
        st.caption("Shared by Retrieve & Document and Modernize below -- pick once, use in both.")
        run = select_project(runs)

    style.section_divider()
    with st.container(key="band-retrieve"):
        retrieve.render_body(run)

    style.section_divider()
    with st.container(key="band-modernize"):
        modernize.render_body(run)


if __name__ == "__main__":
    main()

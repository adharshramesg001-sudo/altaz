"""AtlaZ Streamlit app entry point -- exactly two screens:

- Ingest: point AtlaZ at a repo (local path or git URL); runs the full
  ingestion pipeline in-process, HITL auto-resolved inline (no separate
  review screen).
- Retrieve & Document: pick an ingested project, ask questions against its
  knowledge graph, and generate/download its HLD and LLD.

No configuration is exposed in this app -- LLM provider, Neo4j/Qdrant/
Postgres connection, and confidence threshold all come from `.env`,
silently, on both pages.

Run via `atlaz app` (wraps `streamlit run main.py`), or directly:
    streamlit run src/atlaz/webapp/main.py
"""

from __future__ import annotations

import streamlit as st

from atlaz.webapp import ingest, retrieve, style


def main() -> None:
    st.set_page_config(page_title="AtlaZ", page_icon="🧭", layout="wide")
    style.inject()

    with st.sidebar:
        st.markdown("## 🧭 AtlaZ")
        st.caption("Codebase knowledge, grounded in evidence.")
        st.divider()

    pages = [
        st.Page(ingest.render, title="Ingest", icon="📥", url_path="ingest", default=True),
        st.Page(retrieve.render, title="Retrieve & Document", icon="🔎", url_path="retrieve"),
    ]
    navigation = st.navigation(pages)
    navigation.run()


if __name__ == "__main__":
    main()

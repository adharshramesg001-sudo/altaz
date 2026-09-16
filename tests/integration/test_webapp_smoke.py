"""Smoke tests for the two-screen Streamlit app, using Streamlit's own
AppTest harness. Both pages hit real Neo4j/Postgres (project selection,
reasoning, docgen all read live services, deliberately -- there's no config
screen to point them at fakes), so these live in `tests/integration/`, not
`tests/unit/`, matching this repo's existing test-layout convention.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

WEBAPP_DIR = Path(__file__).resolve().parents[2] / "src" / "atlaz" / "webapp"


def test_ingest_page_renders_without_error(require_neo4j, require_database, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    at = AppTest.from_file(str(WEBAPP_DIR / "ingest.py"), default_timeout=30)
    at.run()

    assert not at.exception
    assert any("Ingest a repository" in h.value for h in at.title)
    assert at.text_input(key="ingest_source") is not None


def test_retrieve_page_renders_without_error(require_neo4j, require_database, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    at = AppTest.from_file(str(WEBAPP_DIR / "retrieve.py"), default_timeout=30)
    at.run()

    # Renders cleanly whether or not any run has completed yet -- either the
    # "no projects" info message, or the project picker + tabs.
    assert not at.exception
    assert any("Retrieve & Document" in h.value for h in at.title)

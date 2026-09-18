"""Smoke tests for the Streamlit app, using Streamlit's own AppTest harness.
All pages hit real Neo4j/Postgres (project selection, reasoning, docgen, and
the enhancement flow all read live services, deliberately -- there's no
config screen to point them at fakes), so these live in
`tests/integration/`, not `tests/unit/`, matching this repo's existing
test-layout convention.

`main.py` is the single-page app users actually run (`atlaz app`); the
per-section modules (`ingest.py`, `retrieve.py`, `modernize.py`) are also
independently runnable via their own `render()` (each picks its own
project), which is what's tested standalone below.
"""

from pathlib import Path

from streamlit.testing.v1 import AppTest

WEBAPP_DIR = Path(__file__).resolve().parents[2] / "src" / "atlaz" / "webapp"


def _has_heading(at: AppTest, text: str) -> bool:
    # `style.page_heading()` renders its <h1> via raw `st.markdown(...,
    # unsafe_allow_html=True)`, never `st.title()`, so headings show up in
    # `at.markdown`, not `at.title`.
    return any(text in m.value for m in at.markdown)


def test_main_page_renders_without_error(require_neo4j, require_database, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("GUIDELINE_STORE_ENABLED", "false")

    at = AppTest.from_file(str(WEBAPP_DIR / "main.py"), default_timeout=30)
    at.run()

    # All three sections stack on one page -- headings for all of them
    # should be present regardless of whether any project has been ingested
    # yet (Retrieve & Document / Modernize degrade to an info message).
    assert not at.exception
    assert _has_heading(at, "Ingest a repository")
    assert at.text_input(key="ingest_source") is not None


def test_ingest_page_renders_without_error(require_neo4j, require_database, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    at = AppTest.from_file(str(WEBAPP_DIR / "ingest.py"), default_timeout=30)
    at.run()

    assert not at.exception
    assert _has_heading(at, "Ingest a repository")
    assert at.text_input(key="ingest_source") is not None


def test_retrieve_page_renders_without_error(require_neo4j, require_database, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    at = AppTest.from_file(str(WEBAPP_DIR / "retrieve.py"), default_timeout=30)
    at.run()

    # Renders cleanly whether or not any run has completed yet -- either the
    # "no projects" info message, or the project picker + tabs.
    assert not at.exception
    assert _has_heading(at, "Retrieve & Document")


def test_modernize_page_renders_without_error(require_neo4j, require_database, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("GUIDELINE_STORE_ENABLED", "false")

    at = AppTest.from_file(str(WEBAPP_DIR / "modernize.py"), default_timeout=30)
    at.run()

    # Renders cleanly whether or not any run has completed yet -- either the
    # "no projects" info message, or the project picker + request textarea.
    assert not at.exception
    assert _has_heading(at, "Modernize")


def test_modernize_page_full_migration_mode_renders_without_error(require_neo4j, require_database, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("GUIDELINE_STORE_ENABLED", "false")

    at = AppTest.from_file(str(WEBAPP_DIR / "modernize.py"), default_timeout=30)
    at.run()
    if not at.radio:
        return  # no completed runs in this environment -- nothing to switch modes on

    at.radio(key="modernize_mode").set_value("🌐 Full migration")
    at.run()

    assert not at.exception
    assert at.text_area(key="migrate_request") is not None

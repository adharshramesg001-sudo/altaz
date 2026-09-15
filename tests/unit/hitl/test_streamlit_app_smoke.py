"""Smoke test for the Streamlit review app using Streamlit's own AppTest
harness. Runs it against a real paused pipeline run (in-process SQLite
checkpoint, no live Neo4j needed since the run pauses before graph_write) to
confirm the app renders the flagged queue without raising."""

import sys
import uuid
from pathlib import Path

from streamlit.testing.v1 import AppTest

from atlaz.llm.client import MockLLMClient
from atlaz.orchestration.graph import build_state_graph
from atlaz.orchestration.serde import build_checkpoint_serializer
from atlaz.shared.config import PipelineConfig

APP_PATH = str(Path(__file__).resolve().parents[3] / "src" / "atlaz" / "hitl" / "streamlit_app.py")


def _pause_a_run(tmp_path: Path) -> tuple[str, Path]:
    (tmp_path / "billing.py").write_text("class Billing:\n    late_fee_rate = 0.05\n")
    checkpoint_path = tmp_path / "checkpoints.sqlite"
    config = PipelineConfig(hitl_enabled=True, checkpoint_db_path=checkpoint_path)

    graph = build_state_graph(config, MockLLMClient())
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
    app = graph.compile(checkpointer=SqliteSaver(conn, serde=build_checkpoint_serializer()))
    thread_id = str(uuid.uuid4())
    app.invoke({"repo_path": str(tmp_path)}, config={"configurable": {"thread_id": thread_id}})
    conn.close()  # release the file lock so the Streamlit app can open its own connection
    return thread_id, checkpoint_path


def test_review_app_renders_pending_items_without_error(tmp_path, monkeypatch):
    thread_id, checkpoint_path = _pause_a_run(tmp_path)

    monkeypatch.setenv("HITL_ENABLED", "true")
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(checkpoint_path))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setattr(sys, "argv", ["streamlit_app.py", "--thread-id", thread_id])

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()

    assert not at.exception
    assert "thread_id" in " ".join(c.value for c in at.caption)
    all_text = [w.value for w in at.markdown] + [w.value for w in at.text]
    assert any("awaiting review" in value for value in all_text)

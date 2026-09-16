"""API tests use a real on-disk checkpoint (created via `run_pipeline`
directly, bypassing Celery) so `GET /runs/{thread_id}` and `POST
.../resolve` exercise the real `get_run_status`/`resume_pipeline` code path.
`POST /ingest` and the Celery-state check inside `GET /runs/{thread_id}`
are the only parts that touch Celery, and are patched -- these tests should
not require a live Redis broker."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from atlaz.api.main import app
from atlaz.llm.client import MockLLMClient
from atlaz.orchestration.runner import run_pipeline
from atlaz.shared.config import PipelineConfig


class FakeWriter:
    def __init__(self, *args, **kwargs):
        pass

    def ensure_schema(self):
        pass

    def write_batch(self, nodes, edges, repo_id=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def checkpoint_env(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CHECKPOINT_DB_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("NEO4J_URI", "bolt://localhost:7687")
    return tmp_path


def _mock_pending_celery_result():
    result = MagicMock()
    result.state = "PENDING"
    return result


def test_ingest_rejects_nonexistent_repo_path(client: TestClient):
    response = client.post("/ingest", json={"repo_path": "/definitely/not/a/real/path"})
    assert response.status_code == 422


def test_ingest_enqueues_celery_task_and_returns_thread_id(client: TestClient, tmp_path: Path):
    with patch("atlaz.api.main.run_ingestion_task") as mock_task:
        response = client.post("/ingest", json={"repo_path": str(tmp_path)})

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["thread_id"]
    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs
    assert call_kwargs["kwargs"]["repo_path"] == str(tmp_path)
    assert call_kwargs["task_id"] == body["thread_id"]


def test_ingest_honors_explicit_thread_id(client: TestClient, tmp_path: Path):
    with patch("atlaz.api.main.run_ingestion_task"):
        response = client.post("/ingest", json={"repo_path": str(tmp_path), "thread_id": "custom-id"})

    assert response.json()["thread_id"] == "custom-id"


def test_run_status_unknown_thread_is_not_found(client: TestClient, checkpoint_env):
    with patch("atlaz.api.main.AsyncResult", return_value=_mock_pending_celery_result()):
        response = client.get("/runs/does-not-exist")

    assert response.status_code == 200
    assert response.json()["status"] == "not_found"


def test_run_status_reports_complete_run(client: TestClient, checkpoint_env):
    (checkpoint_env / "billing.py").write_text("class Billing:\n    late_fee_rate = 0.05\n")
    config = PipelineConfig(hitl_enabled=False, checkpoint_db_path=checkpoint_env / "checkpoints.sqlite")
    result = run_pipeline(str(checkpoint_env), config, llm_client=MockLLMClient(), writer_factory=lambda: FakeWriter())

    with patch("atlaz.api.main.AsyncResult", return_value=_mock_pending_celery_result()):
        response = client.get(f"/runs/{result.thread_id}")

    body = response.json()
    assert body["status"] == "complete"
    assert body["nodes_written"] > 0


def test_run_status_reports_failed_task(client: TestClient, checkpoint_env):
    failed_result = MagicMock()
    failed_result.state = "FAILURE"
    failed_result.result = RuntimeError("boom")

    with patch("atlaz.api.main.AsyncResult", return_value=failed_result):
        response = client.get("/runs/some-thread")

    body = response.json()
    assert body["status"] == "failed"
    assert "boom" in body["error"]


def test_resolve_run_completes_a_paused_run(client: TestClient, checkpoint_env, monkeypatch):
    (checkpoint_env / "billing.py").write_text("class Billing:\n    late_fee_rate = 0.05\n")
    config = PipelineConfig(hitl_enabled=True, checkpoint_db_path=checkpoint_env / "checkpoints.sqlite")
    result = run_pipeline(str(checkpoint_env), config, llm_client=MockLLMClient(), writer_factory=lambda: FakeWriter())
    assert result.status == "pending_review"

    # The API's own POST /runs/{id}/resolve calls the real `resume_pipeline`
    # with no writer_factory override, so this patches the writer it
    # constructs by default to avoid the request touching a real Neo4j.
    monkeypatch.setattr("atlaz.orchestration.nodes.Neo4jWriter", FakeWriter)

    with patch("atlaz.api.main.AsyncResult", return_value=_mock_pending_celery_result()):
        response = client.post(f"/runs/{result.thread_id}/resolve", json={"resolutions": []})

    body = response.json()
    assert body["status"] == "complete"


def test_resolve_run_404s_when_nothing_pending(client: TestClient, checkpoint_env):
    response = client.post("/runs/never-started/resolve", json={"resolutions": []})
    assert response.status_code == 404

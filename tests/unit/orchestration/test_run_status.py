"""`get_run_status` reads the checkpoint file directly, so (unlike the other
orchestration tests) it needs a real on-disk SQLite checkpoint -- the whole
point is that a *separate* `compile_graph()` call (a fresh connection, as a
status-check API request would make) can still see it."""

import uuid
from pathlib import Path

from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.llm.client import MockLLMClient
from atlaz.orchestration.runner import get_run_status, resume_pipeline, run_pipeline
from atlaz.shared.config import PipelineConfig


class FakeWriter:
    def ensure_schema(self):
        pass

    def write_batch(self, nodes, edges, repo_id=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass


def _config(tmp_path: Path, hitl_enabled: bool) -> PipelineConfig:
    return PipelineConfig(hitl_enabled=hitl_enabled, checkpoint_db_path=tmp_path / "checkpoints.sqlite")


def _write_repo(tmp_path: Path) -> str:
    (tmp_path / "billing.py").write_text("class Billing:\n    late_fee_rate = 0.05\n")
    return str(tmp_path)


def test_unknown_thread_id_is_not_found(tmp_path: Path):
    config = _config(tmp_path, hitl_enabled=False)
    status = get_run_status(str(uuid.uuid4()), config, llm_client=MockLLMClient())
    assert status.status == "not_found"


def test_completed_run_reports_complete_with_counts(tmp_path: Path):
    repo_path = _write_repo(tmp_path)
    config = _config(tmp_path, hitl_enabled=False)

    result = run_pipeline(repo_path, config, llm_client=MockLLMClient(), writer_factory=lambda: FakeWriter())
    assert result.status == "complete"

    status = get_run_status(result.thread_id, config, llm_client=MockLLMClient())
    assert status.status == "complete"
    assert status.nodes_written is not None and status.nodes_written > 0


def test_paused_run_reports_pending_review_with_flagged_items(tmp_path: Path):
    repo_path = _write_repo(tmp_path)
    config = _config(tmp_path, hitl_enabled=True)

    result = run_pipeline(repo_path, config, llm_client=MockLLMClient(), writer_factory=lambda: FakeWriter())
    assert result.status == "pending_review"

    status = get_run_status(result.thread_id, config, llm_client=MockLLMClient())
    assert status.status == "pending_review"
    assert status.flagged_items
    assert any(item.kind.value == "gap_confirmation" for item in status.flagged_items)

    resolutions = auto_resolve(status.flagged_items)
    resume_pipeline(
        result.thread_id, resolutions, config, llm_client=MockLLMClient(), writer_factory=lambda: FakeWriter()
    )

    final_status = get_run_status(result.thread_id, config, llm_client=MockLLMClient())
    assert final_status.status == "complete"

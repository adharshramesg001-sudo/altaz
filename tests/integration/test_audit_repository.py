"""Integration test against the real `atlaz` audit database (skipped
automatically if unreachable). Uses a `pytest-` prefixed thread_id and
deletes exactly that row's data on teardown -- this Postgres instance is
shared with other projects (e.g. `ignitezsdlc`), so no test here may touch
anything outside its own rows, and even within its own database, only rows
this test itself created.
"""

import pytest
from sqlalchemy import text

from atlaz.audit.models import HitlResolution, PipelineRun
from atlaz.audit.repository import (
    list_completed_runs,
    record_resolutions,
    record_run_started,
    record_run_status,
)
from atlaz.hitl.models import ReviewAction, ReviewResolution

TEST_THREAD_ID = "pytest-atlaz-integration-audit"


@pytest.fixture
def clean_thread(database_config, require_database):
    from atlaz.audit.db import session_scope

    yield TEST_THREAD_ID
    with session_scope(database_config) as session:
        session.execute(text("DELETE FROM atlaz.hitl_resolutions WHERE thread_id = :tid"), {"tid": TEST_THREAD_ID})
        session.execute(text("DELETE FROM atlaz.pipeline_runs WHERE thread_id = :tid"), {"tid": TEST_THREAD_ID})


def test_full_audit_lifecycle(database_config, clean_thread):
    from atlaz.audit.db import session_scope

    record_run_started(TEST_THREAD_ID, "/tmp/some-repo", hitl_enabled=True, config=database_config)

    with session_scope(database_config) as session:
        run = session.get(PipelineRun, TEST_THREAD_ID)
        assert run is not None
        assert run.status == "running"
        assert run.hitl_enabled is True

    # a second "started" call for the same thread must not duplicate the row
    record_run_started(TEST_THREAD_ID, "/tmp/some-repo", hitl_enabled=True, config=database_config)
    with session_scope(database_config) as session:
        count = session.query(PipelineRun).filter_by(thread_id=TEST_THREAD_ID).count()
        assert count == 1

    resolutions = [
        ReviewResolution(item_id="domain_a::business_case_vision", action=ReviewAction.REJECT, reviewer="alice"),
        ReviewResolution(item_id="low_confidence::x::y", action=ReviewAction.ACCEPT, reviewer="alice"),
    ]
    record_resolutions(TEST_THREAD_ID, resolutions, config=database_config)

    with session_scope(database_config) as session:
        rows = session.query(HitlResolution).filter_by(thread_id=TEST_THREAD_ID).all()
        assert len(rows) == 2
        assert {r.action for r in rows} == {"reject", "accept"}
        assert all(r.reviewer == "alice" for r in rows)

    record_run_status(TEST_THREAD_ID, "complete", nodes_written=42, edges_written=7, config=database_config)

    with session_scope(database_config) as session:
        run = session.get(PipelineRun, TEST_THREAD_ID)
        assert run.status == "complete"
        assert run.nodes_written == 42
        assert run.edges_written == 7


def test_list_completed_runs_includes_only_complete_status(database_config, clean_thread):
    record_run_started(TEST_THREAD_ID, "/tmp/some-repo", hitl_enabled=False, config=database_config, repo_id="some-repo")

    assert TEST_THREAD_ID not in {r.thread_id for r in list_completed_runs(config=database_config)}

    record_run_status(TEST_THREAD_ID, "complete", nodes_written=1, edges_written=1, config=database_config)

    completed = list_completed_runs(config=database_config)
    match = next(r for r in completed if r.thread_id == TEST_THREAD_ID)
    assert match.repo_id == "some-repo"

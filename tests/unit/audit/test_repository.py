"""Unit tests verify the graceful-degradation contract without a real
database: every repository function must swallow its own errors rather
than raise, since an audit-log outage must never break the pipeline."""

from unittest.mock import patch

from atlaz.audit.repository import record_resolutions, record_run_started, record_run_status
from atlaz.hitl.models import ReviewAction, ReviewResolution
from atlaz.shared.config import DatabaseConfig

_UNREACHABLE_CONFIG = DatabaseConfig(url="postgresql+psycopg://nobody:nobody@localhost:1/does-not-exist")


def test_record_run_started_does_not_raise_when_db_unreachable():
    record_run_started("t1", "/repo", True, config=_UNREACHABLE_CONFIG)


def test_record_run_status_does_not_raise_when_db_unreachable():
    record_run_status("t1", "complete", nodes_written=1, edges_written=1, config=_UNREACHABLE_CONFIG)


def test_record_resolutions_does_not_raise_when_db_unreachable():
    resolutions = [ReviewResolution(item_id="i1", action=ReviewAction.ACCEPT, reviewer="r")]
    record_resolutions("t1", resolutions, config=_UNREACHABLE_CONFIG)


def test_record_run_started_skips_existing_run():
    with patch("atlaz.audit.repository.session_scope") as mock_scope:
        session = mock_scope.return_value.__enter__.return_value
        session.get.return_value = object()  # an existing row

        record_run_started("t1", "/repo", True)

        session.add.assert_not_called()

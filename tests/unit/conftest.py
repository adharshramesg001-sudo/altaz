"""Applies to every test under tests/unit/: guarantees no unit test can
write to the real audit database, regardless of what `PipelineConfig` it
constructs.

`PipelineConfig()`'s default `DatabaseConfig` points at
`postgresql+psycopg://postgres:postgres@localhost:5432/atlaz` -- since
`atlaz db init` makes that URL genuinely reachable on a dev machine, a unit
test that calls `run_pipeline`/`resume_pipeline` without explicitly
isolating `database=` would otherwise silently write real audit rows on
every test run (`record_run_started`/`record_run_status`/
`record_resolutions`'s broad except-and-log only degrades gracefully when
the database is actually unreachable -- it has no way to know a passing
connection is undesired). Patching `session_scope` to always fail is a single, un-bypassable choke
point: every function in `atlaz.audit.repository` goes through it -- and
must be patched *there* (`atlaz.audit.repository.session_scope`), not on
`atlaz.audit.db`, since `from atlaz.audit.db import session_scope` already
bound the name locally in that module at import time.
"""

from contextlib import contextmanager

import pytest


@pytest.fixture(autouse=True)
def _no_real_audit_writes_in_unit_tests(monkeypatch):
    @contextmanager
    def _always_unreachable(config=None):
        raise ConnectionError("audit database access is disabled in the unit test suite")
        yield  # pragma: no cover - unreachable, but keeps this a generator function

    monkeypatch.setattr("atlaz.audit.repository.session_scope", _always_unreachable)

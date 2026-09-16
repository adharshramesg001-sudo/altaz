"""Central logging setup for every AtlaZ process (CLI, FastAPI, Celery worker).

Every module logs via `logging.getLogger(__name__)`, but without a handler
configured on the root logger those calls are silently dropped (or, at best,
print an unformatted "no handlers found" fallback) -- the exact reason the
`azure` provider failure showed up as a bare traceback with no context about
which thread_id/repo_path was running. Each process entry point calls
`configure_logging()` once, so app log lines actually appear with a
timestamp, level, and originating module.
"""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

_configured = False


def configure_logging(level: str | None = None) -> None:
    """Idempotent: safe to call from multiple entry points (e.g. a module
    that's both imported directly and run under uvicorn/celery).

    Called at process startup, before `PipelineConfig.from_env()` runs (it's
    invoked per-request/per-task, not at import time) -- so `.env` is loaded
    here too, otherwise LOG_LEVEL from `.env` would be invisible until the
    first pipeline config load."""
    global _configured
    if _configured:
        return

    load_dotenv(override=False)
    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).strip().upper()
    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # The neo4j driver logs one very verbose raw notification object per
    # already-existing constraint/index at INFO -- pure noise against our
    # own app-level messages, so it's quieted independently of LOG_LEVEL.
    logging.getLogger("neo4j.notifications").setLevel(logging.WARNING)

    _configured = True

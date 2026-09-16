"""Celery application instance.

Run the worker with:
    celery -A atlaz.worker.celery_app.celery_app worker --loglevel=info

Configuration comes from `CeleryConfig.from_env()` (`CELERY_BROKER_URL`,
`CELERY_RESULT_BACKEND` -- Redis by default, matching `docker-compose.yml`).
JSON serialization only: task arguments and return values must be plain
JSON-safe types, never the project's own dataclasses -- see
`atlaz.worker.tasks` for how the ingestion task keeps to that.
"""

from __future__ import annotations

import logging

from celery import Celery

from atlaz.shared.config import CeleryConfig
from atlaz.shared.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


def build_celery_app(config: CeleryConfig | None = None) -> Celery:
    config = config or CeleryConfig.from_env()
    logger.info("Building Celery app: broker=%s backend=%s", config.broker_url, config.result_backend)
    app = Celery("atlaz", broker=config.broker_url, backend=config.result_backend, include=["atlaz.worker.tasks"])
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_track_started=True,
        result_expires=None,  # keep results around; GET /runs/{id} may be polled long after completion
    )
    return app


celery_app = build_celery_app()

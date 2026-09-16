"""Single entry point for setting up the audit database: create the
database (if missing), create its schema, then run Alembic migrations up to
head. Both `atlaz db init` (`atlaz/cli.py`) and the standalone
`scripts/migrate_db.py` call this -- one implementation, two ways to run it.
"""

from __future__ import annotations

from pathlib import Path

from atlaz.audit.db import ensure_database_exists, ensure_schema_exists
from atlaz.shared.config import DatabaseConfig

REPO_ROOT = Path(__file__).resolve().parents[3]


def migrate(config: DatabaseConfig | None = None) -> None:
    from alembic.config import Config

    from alembic import command

    config = config or DatabaseConfig.from_env()

    created = ensure_database_exists(config)
    print(f"Database ready ({'created' if created else 'already existed'}).")

    ensure_schema_exists(config)
    print(f"Schema '{config.schema}' ready.")

    alembic_cfg = Config(str(REPO_ROOT / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    command.upgrade(alembic_cfg, "head")
    print("Migrations applied.")

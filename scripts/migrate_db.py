#!/usr/bin/env python3
"""Standalone migration runner for the AtlaZ audit database.

Creates the `atlaz` database (if missing), creates its `atlaz` schema, and
runs Alembic migrations up to head -- the same steps `atlaz db init` runs,
exposed here as a plain script for anyone who wants a single obvious command
to set up (or update) the audit database without going through the full CLI.

Usage:
    python scripts/migrate_db.py
    # or, if executable (chmod +x scripts/migrate_db.py):
    ./scripts/migrate_db.py

Configuration comes entirely from the environment (`.env` in the repo root,
or real env vars) -- see DATABASE_URL / ADMIN_DATABASE_URL / DB_SCHEMA in
.env.example. Requires an editable/source checkout: it adds src/ to
sys.path itself, so it also works before `pip install -e .`.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv

from atlaz.audit.migrate import migrate


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    migrate()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

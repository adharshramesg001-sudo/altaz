"""Engine/session management for the audit database, plus the one-time
`ensure_database_exists` step `atlaz db init` runs before Alembic migrates
the schema.

`ensure_database_exists` connects via `admin_url` (a database that already
exists -- the server's default `postgres`) because `CREATE DATABASE` cannot
run inside a transaction against the database being created; SQLAlchemy/psycopg
both wrap statements in a transaction by default, so this uses `AUTOCOMMIT`
isolation explicitly.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from atlaz.shared.config import DatabaseConfig


def _database_name_from_url(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def ensure_database_exists(config: DatabaseConfig) -> bool:
    """Creates the target database if it doesn't exist yet. Returns True if
    it was created, False if it already existed."""
    target_db = _database_name_from_url(config.url)
    admin_engine = create_engine(config.admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target_db}
            ).scalar()
            if exists:
                return False
            # Database names can't be parameterized in DDL; target_db is
            # sourced from our own config (an env var this app's operator
            # controls), not from request input, so this is not building a
            # query from untrusted data.
            conn.execute(text(f'CREATE DATABASE "{target_db}"'))
            return True
    finally:
        admin_engine.dispose()


def ensure_schema_exists(config: DatabaseConfig) -> None:
    engine = create_engine(config.url)
    try:
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{config.schema}"'))
    finally:
        engine.dispose()


_engines_by_url: dict[str, Engine] = {}
_session_factories_by_url: dict[str, sessionmaker[Session]] = {}


def get_engine(config: DatabaseConfig | None = None):
    """Cached per database URL, not as a single global -- a test pointed at
    a different `DatabaseConfig` than a previous call must get its own
    engine, not silently reuse whichever one happened to be created first."""
    url = (config or DatabaseConfig.from_env()).url
    if url not in _engines_by_url:
        _engines_by_url[url] = create_engine(url)
    return _engines_by_url[url]


def get_session_factory(config: DatabaseConfig | None = None) -> sessionmaker[Session]:
    url = (config or DatabaseConfig.from_env()).url
    if url not in _session_factories_by_url:
        _session_factories_by_url[url] = sessionmaker(bind=get_engine(config), expire_on_commit=False)
    return _session_factories_by_url[url]


@contextmanager
def session_scope(config: DatabaseConfig | None = None) -> Iterator[Session]:
    session = get_session_factory(config)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

import pytest

from atlaz.shared.config import DatabaseConfig, Neo4jConfig


@pytest.fixture(scope="session")
def neo4j_config() -> Neo4jConfig:
    return Neo4jConfig()  # defaults match docker-compose.yml


@pytest.fixture(scope="session")
def require_neo4j(neo4j_config: Neo4jConfig):
    from neo4j import GraphDatabase
    from neo4j.exceptions import ServiceUnavailable

    driver = GraphDatabase.driver(neo4j_config.uri, auth=(neo4j_config.user, neo4j_config.password))
    try:
        driver.verify_connectivity()
    except ServiceUnavailable:
        pytest.skip(f"Neo4j is not reachable at {neo4j_config.uri} -- run `docker compose up -d` first.")
    finally:
        driver.close()


@pytest.fixture(scope="session")
def database_config() -> DatabaseConfig:
    return DatabaseConfig.from_env()  # defaults match `atlaz db init`


@pytest.fixture(scope="session")
def require_database(database_config: DatabaseConfig):
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    engine = create_engine(database_config.url)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip(
            f"Postgres audit database is not reachable at {database_config.url} -- run `atlaz db init` first."
        )
    finally:
        engine.dispose()

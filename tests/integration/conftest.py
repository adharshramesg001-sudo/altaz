import pytest

from atlaz.shared.config import Neo4jConfig


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

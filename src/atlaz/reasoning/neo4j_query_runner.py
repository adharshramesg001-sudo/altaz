"""Real `QueryRunner` implementation (LLD Section 12.1) -- reads only, so it
is deliberately a thin wrapper around a single-statement Cypher execution
rather than sharing `Neo4jWriter`'s write-oriented session helpers.
"""

from __future__ import annotations

from typing import Self

from neo4j import Driver, GraphDatabase

from atlaz.shared.config import Neo4jConfig


class Neo4jReasoningStore:
    def __init__(self, config: Neo4jConfig, driver: Driver | None = None) -> None:
        self.config = config
        self._owns_driver = driver is None
        self.driver: Driver = driver or GraphDatabase.driver(config.uri, auth=(config.user, config.password))

    def close(self) -> None:
        if self._owns_driver:
            self.driver.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def run(self, cypher: str, params: dict) -> list[dict]:
        with self.driver.session(database=self.config.database) as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

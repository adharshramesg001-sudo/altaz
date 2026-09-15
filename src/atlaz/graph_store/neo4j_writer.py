"""Neo4jWriter (LLD Section 11).

Every node write is a MERGE, never a CREATE, keyed on its natural id, so
re-running the pipeline on an updated repo updates `last_verified` rather
than duplicating nodes. `conflicts_with` edges are the only edge type this
writer will ever be asked to create post-HITL only -- the caller (the
merge/HITL layer) is responsible for that ordering; this class just writes
whatever batch it is given.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Self

from neo4j import Driver, GraphDatabase

from atlaz.graph_store.schema import (
    CONSTRAINT_STATEMENTS,
    INDEX_STATEMENTS,
    NATURAL_KEY_FIELD,
    GraphEdge,
    GraphNode,
)
from atlaz.shared.config import Neo4jConfig


class Neo4jWriter:
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

    def ensure_schema(self) -> None:
        with self.driver.session(database=self.config.database) as session:
            for statement in CONSTRAINT_STATEMENTS + INDEX_STATEMENTS:
                session.run(statement)

    def write_batch(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge]) -> None:
        nodes = list(nodes)
        edges = list(edges)
        run_timestamp = time.time()
        with self.driver.session(database=self.config.database) as session:
            session.execute_write(self._merge_nodes, nodes, run_timestamp)
            session.execute_write(self._merge_edges, edges)

    @staticmethod
    def _merge_nodes(tx, nodes: list[GraphNode], run_timestamp: float) -> None:
        for node in nodes:
            properties = dict(node.properties)
            properties[node.key_field] = node.key_value
            properties["last_verified"] = run_timestamp
            query = (
                f"MERGE (n:{node.label.value} {{{node.key_field}: $key_value}}) "
                "SET n += $properties"
            )
            tx.run(query, key_value=node.key_value, properties=properties)

    @staticmethod
    def _merge_edges(tx, edges: list[GraphEdge]) -> None:
        for edge in edges:
            source_key_field = NATURAL_KEY_FIELD[edge.source_label]
            target_key_field = NATURAL_KEY_FIELD[edge.target_label]
            query = (
                f"MATCH (a:{edge.source_label.value} {{{source_key_field}: $source_key}}) "
                f"MATCH (b:{edge.target_label.value} {{{target_key_field}: $target_key}}) "
                f"MERGE (a)-[r:{edge.edge_type.value.upper()}]->(b) "
                "SET r += $properties"
            )
            tx.run(query, source_key=edge.source_key, target_key=edge.target_key, properties=dict(edge.properties))

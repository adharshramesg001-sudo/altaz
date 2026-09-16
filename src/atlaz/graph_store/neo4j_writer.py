"""Neo4jWriter (LLD Section 11).

Every node write is a MERGE, never a CREATE, keyed on its natural id, so
re-running the pipeline on an updated repo updates `last_verified` rather
than duplicating nodes. `conflicts_with` edges are the only edge type this
writer will ever be asked to create post-HITL only -- the caller (the
merge/HITL layer) is responsible for that ordering; this class just writes
whatever batch it is given.

`write_batch`'s optional `repo_id` stamps every node (not just `Repository`/
`Database`, which already carry it via their own key) with a `repo_id`
property. Neo4j in this project is a single shared instance across every
repo ever ingested, and most node labels (`File`, `Class`, `Method`,
`Service`, `BusinessCapability`, ...) have no other run-scoping property --
without this, a cross-run reader (e.g. `atlaz.docgen`) has no way to tell
which ingested repo a given node belongs to and would silently blend
multiple repos' facts together. This was caught by exactly that failure
mode during HLD/LLD generation testing, not found by inspection.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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
        logger.info(
            "Neo4j schema ensured: %d constraint(s), %d index(es)",
            len(CONSTRAINT_STATEMENTS), len(INDEX_STATEMENTS),
        )

    def write_batch(self, nodes: Iterable[GraphNode], edges: Iterable[GraphEdge], repo_id: str | None = None) -> None:
        nodes = list(nodes)
        edges = list(edges)
        run_timestamp = time.time()
        try:
            with self.driver.session(database=self.config.database) as session:
                session.execute_write(self._merge_nodes, nodes, run_timestamp, repo_id)
                session.execute_write(self._merge_edges, edges)
        except Exception:
            logger.exception(
                "Neo4j write_batch failed: %d node(s), %d edge(s), database=%s",
                len(nodes), len(edges), self.config.database,
            )
            raise
        logger.info("Neo4j write_batch succeeded: %d node(s), %d edge(s) merged", len(nodes), len(edges))

    @staticmethod
    def _merge_nodes(tx, nodes: list[GraphNode], run_timestamp: float, repo_id: str | None) -> None:
        for node in nodes:
            properties = dict(node.properties)
            properties[node.key_field] = node.key_value
            properties["last_verified"] = run_timestamp
            if repo_id is not None:
                properties["repo_id"] = repo_id
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

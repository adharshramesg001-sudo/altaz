"""Integration test against a real Neo4j instance (skipped automatically if
unreachable). Uses a `pytest::` key-value prefix throughout and deletes
exactly those nodes on teardown -- this instance is shared with other
projects (e.g. Cortex's GraphRAG graph), so no test here may touch anything
outside its own prefixed nodes.
"""

import pytest

from atlaz.graph_store.neo4j_writer import Neo4jWriter
from atlaz.graph_store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel

TEST_PREFIX = "pytest::atlaz-integration"


@pytest.fixture
def writer(neo4j_config, require_neo4j):
    w = Neo4jWriter(neo4j_config)
    yield w
    with w.driver.session(database=neo4j_config.database) as session:
        session.run(
            "MATCH (n) WHERE n.rule_id STARTS WITH $prefix OR n.table_id STARTS WITH $prefix "
            "DETACH DELETE n",
            prefix=TEST_PREFIX,
        )
    w.close()


def test_ensure_schema_is_idempotent(writer: Neo4jWriter):
    writer.ensure_schema()
    writer.ensure_schema()  # must not raise on the second run (IF NOT EXISTS)


def test_write_batch_merges_nodes_and_edges(writer: Neo4jWriter, neo4j_config):
    rule_node = GraphNode(
        label=NodeLabel.BUSINESS_RULE,
        key_value=f"{TEST_PREFIX}::rule1",
        properties={"description": "test rule", "literal_value": "0.05", "tier": "extractable", "confidence": 1.0},
    )
    entity_node = GraphNode(
        label=NodeLabel.TABLE,
        key_value=f"{TEST_PREFIX}::entity1",
        properties={"source_kind": "orm_model", "tier": "extractable", "confidence": 1.0},
    )
    edge = GraphEdge(
        edge_type=EdgeType.CONFLICTS_WITH,
        source_label=NodeLabel.BUSINESS_RULE,
        source_key=rule_node.key_value,
        target_label=NodeLabel.TABLE,
        target_key=entity_node.key_value,
        properties={"status": "auto_resolved"},
    )

    writer.write_batch([rule_node, entity_node], [edge])

    with writer.driver.session(database=neo4j_config.database) as session:
        result = session.run(
            "MATCH (r:BusinessRule {rule_id: $rule_id})-[c:CONFLICTS_WITH]->(e:Table {table_id: $entity_id}) "
            "RETURN r.description AS description, c.status AS status, r.last_verified AS last_verified",
            rule_id=rule_node.key_value,
            entity_id=entity_node.key_value,
        )
        record = result.single()

    assert record is not None
    assert record["description"] == "test rule"
    assert record["status"] == "auto_resolved"
    assert record["last_verified"] is not None


def test_write_batch_is_idempotent_via_merge(writer: Neo4jWriter, neo4j_config):
    node = GraphNode(
        label=NodeLabel.BUSINESS_RULE,
        key_value=f"{TEST_PREFIX}::rule2",
        properties={"description": "v1", "literal_value": "1", "tier": "extractable", "confidence": 1.0},
    )
    writer.write_batch([node], [])
    node.properties["description"] = "v2"
    writer.write_batch([node], [])

    with writer.driver.session(database=neo4j_config.database) as session:
        result = session.run(
            "MATCH (r:BusinessRule {rule_id: $rule_id}) RETURN count(r) AS c, r.description AS description",
            rule_id=node.key_value,
        )
        record = result.single()

    assert record["c"] == 1  # MERGE, not CREATE -- no duplicate node
    assert record["description"] == "v2"  # properties updated in place


def test_write_batch_stamps_repo_id_on_every_node(writer: Neo4jWriter, neo4j_config):
    """Regression test: without this, a cross-run reader (atlaz.docgen) has
    no way to scope a query to one ingested repo, and silently blends every
    repo ever written to this shared Neo4j instance together."""
    node = GraphNode(
        label=NodeLabel.BUSINESS_RULE,
        key_value=f"{TEST_PREFIX}::rule3",
        properties={"description": "v1", "literal_value": "1", "tier": "extractable", "confidence": 1.0},
    )
    writer.write_batch([node], [], repo_id="pytest-repo-scoping-check")

    with writer.driver.session(database=neo4j_config.database) as session:
        record = session.run(
            "MATCH (r:BusinessRule {rule_id: $rule_id}) RETURN r.repo_id AS repo_id", rule_id=node.key_value
        ).single()

    assert record["repo_id"] == "pytest-repo-scoping-check"

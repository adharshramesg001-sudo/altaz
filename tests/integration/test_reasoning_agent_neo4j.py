"""Integration test: writes a small `pytest::`-prefixed fragment into the
real Neo4j instance via `Neo4jWriter`, then reads it back through
`Neo4jReasoningStore` + `ReasoningAgent` in DRIFT mode -- the one mode that
needs no LLM-generated Cypher, so this is a genuine end-to-end check of the
graph schema round-trip. Cleans up exactly its own nodes on teardown.
"""

import pytest

from atlaz.graph_store.neo4j_writer import Neo4jWriter
from atlaz.graph_store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from atlaz.llm.client import MockLLMClient
from atlaz.reasoning.neo4j_query_runner import Neo4jReasoningStore
from atlaz.reasoning.reasoning_agent import ReasoningAgent, ReasoningMode

TEST_PREFIX = "pytest::atlaz-reasoning-integration"


@pytest.fixture
def seeded_conflict(neo4j_config, require_neo4j):
    writer = Neo4jWriter(neo4j_config)
    rule_key = f"{TEST_PREFIX}::rule"
    entity_key = f"{TEST_PREFIX}::entity"
    writer.write_batch(
        [
            GraphNode(label=NodeLabel.BUSINESS_RULE, key_value=rule_key, properties={"literal_value": "0.05"}),
            GraphNode(label=NodeLabel.DATA_ENTITY, key_value=entity_key, properties={"source_kind": "orm_model"}),
        ],
        [
            GraphEdge(
                edge_type=EdgeType.CONFLICTS_WITH,
                source_label=NodeLabel.BUSINESS_RULE,
                source_key=rule_key,
                target_label=NodeLabel.DATA_ENTITY,
                target_key=entity_key,
                properties={"rule_value": "0.05", "entity_value": "0.045", "unresolved": True},
            )
        ],
    )
    yield rule_key, entity_key
    with writer.driver.session(database=neo4j_config.database) as session:
        session.run(
            "MATCH (n) WHERE n.rule_id STARTS WITH $prefix OR n.entity_name STARTS WITH $prefix DETACH DELETE n",
            prefix=TEST_PREFIX,
        )
    writer.close()


def test_drift_mode_reads_real_conflicts_with_edge(neo4j_config, seeded_conflict):
    rule_key, entity_key = seeded_conflict
    with Neo4jReasoningStore(neo4j_config) as store:
        agent = ReasoningAgent(MockLLMClient(), store.run)
        result = agent.answer("Where does intent diverge from implementation?", ReasoningMode.DRIFT)

    assert rule_key in result.cited_nodes
    assert entity_key in result.cited_nodes

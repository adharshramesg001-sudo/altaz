import pytest

from atlaz.reasoning.cypher_safety import UnsafeCypherError, ensure_read_only


def test_allows_plain_match_return():
    assert ensure_read_only("MATCH (n:BusinessRule) RETURN n") == "MATCH (n:BusinessRule) RETURN n"


def test_allows_optional_match_and_with():
    query = "MATCH (n) WITH n OPTIONAL MATCH (n)-[:owns]->(m) RETURN n, m"
    assert ensure_read_only(query) == query


def test_rejects_query_not_starting_with_read_keyword():
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("CREATE (n:Evil) RETURN n")


def test_rejects_delete_hidden_after_match():
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("MATCH (n) DETACH DELETE n")


def test_rejects_empty_query():
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("   ")


def test_rejects_procedure_call():
    with pytest.raises(UnsafeCypherError):
        ensure_read_only("MATCH (n) CALL apoc.trigger.add('x','y',{}) RETURN n")

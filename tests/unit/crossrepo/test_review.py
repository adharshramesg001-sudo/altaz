import pytest

from atlaz.crossrepo.review import fetch_unconfirmed, set_status


def test_fetch_unconfirmed_merges_sync_and_async_sorted_by_confidence():
    def runner(cypher, params):
        if "CALLS_SERVICE" in cypher:
            return [
                {
                    "rel_id": 1,
                    "source": "checkout",
                    "source_repo_id": "repo-a",
                    "target": "order-service",
                    "target_repo_id": "repo-b",
                    "confidence": 0.85,
                    "matched_on": "service_name_and_route",
                }
            ]
        return [
            {
                "rel_id": 2,
                "rel_type": "PUBLISHES",
                "service": "checkout",
                "topic": "ordercreated",
                "confidence": 0.7,
                "library": "kafka",
            }
        ]

    links = fetch_unconfirmed(runner, "repo-a")

    assert [link.rel_id for link in links] == [2, 1]  # sorted ascending by confidence
    assert links[0].kind == "publishes"
    assert links[0].target_repo_id is None
    assert links[1].kind == "calls_service"
    assert links[1].target_repo_id == "repo-b"


def test_set_status_issues_update_by_relationship_id():
    queries = []

    def runner(cypher, params):
        queries.append((cypher, params))
        return []

    set_status(runner, 42, "confirmed")

    cypher, params = queries[0]
    assert "id(r) = $rel_id" in cypher
    assert params == {"rel_id": 42, "status": "confirmed"}


def test_set_status_rejects_unknown_status():
    with pytest.raises(ValueError, match="status must be one of"):
        set_status(lambda cypher, params: [], 1, "maybe")

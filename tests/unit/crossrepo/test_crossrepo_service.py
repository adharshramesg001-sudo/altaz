from dataclasses import dataclass

import pytest

from atlaz.crossrepo.models import ServiceLinkCandidate
from atlaz.crossrepo.service import CrossRepoLinkService
from atlaz.shared.evidence import Evidence


@dataclass
class _FakeRun:
    repo_id: str
    repo_path: str = "/tmp/somewhere"


def test_find_candidates_raises_for_unknown_thread(monkeypatch):
    monkeypatch.setattr("atlaz.crossrepo.service.get_run", lambda thread_id, config: None)
    service = CrossRepoLinkService(lambda cypher, params: [])

    with pytest.raises(ValueError, match="unknown-thread"):
        service.find_candidates("unknown-thread", "other")


def test_find_candidates_scopes_both_repos_and_correlates_both_directions(monkeypatch):
    runs = {"t1": _FakeRun(repo_id="repo-a"), "t2": _FakeRun(repo_id="repo-b")}
    monkeypatch.setattr("atlaz.crossrepo.service.get_run", lambda thread_id, config: runs[thread_id])
    monkeypatch.setattr("atlaz.crossrepo.service.fetch_project_facts", lambda runner, thread_id, repo_id: object())
    monkeypatch.setattr("atlaz.crossrepo.service.scan_outbound_calls", lambda repo_path: [])
    monkeypatch.setattr("atlaz.crossrepo.service.scan_declared_service_names", lambda repo_path: set())

    calls = []

    def fake_correlate(source_facts, source_signals, target_facts, target_declared_names):
        calls.append((source_facts, target_facts))
        return []

    monkeypatch.setattr("atlaz.crossrepo.service.correlate", fake_correlate)

    service = CrossRepoLinkService(lambda cypher, params: [])
    result = service.find_candidates("t1", "t2")

    assert result == []
    assert len(calls) == 2  # A->B and B->A


def test_write_persists_edge_with_repo_id_qualified_match(monkeypatch):
    monkeypatch.setattr("atlaz.crossrepo.service.record_evidence", lambda records, config: None)
    queries = []

    def runner(cypher, params):
        queries.append((cypher, params))
        return []

    candidate = ServiceLinkCandidate(
        source_repo_id="repo-a",
        source_service="checkout",
        target_repo_id="repo-b",
        target_service="order-service",
        matched_on="service_name_and_route",
        confidence=0.85,
        evidence=[Evidence(file="client.py", line=4)],
    )

    service = CrossRepoLinkService(runner)
    written = service.write([candidate])

    assert written == 1
    assert len(queries) == 1
    cypher, params = queries[0]
    assert "repo_id: $a_repo" in cypher
    assert "repo_id: $b_repo" in cypher
    assert params["a_name"] == "checkout"
    assert params["a_repo"] == "repo-a"
    assert params["b_name"] == "order-service"
    assert params["b_repo"] == "repo-b"
    assert params["properties"]["status"] == "unconfirmed"
    assert params["properties"]["confidence"] == 0.85

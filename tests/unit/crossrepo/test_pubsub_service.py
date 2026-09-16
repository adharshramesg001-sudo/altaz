from dataclasses import dataclass
from typing import ClassVar

import pytest

from atlaz.crossrepo.models import PubSubFinding
from atlaz.crossrepo.pubsub_service import PubSubLinkService
from atlaz.shared.evidence import Evidence


@dataclass
class _FakeRun:
    repo_id: str
    repo_path: str = "/tmp/somewhere"


def test_scan_raises_for_unknown_thread(monkeypatch):
    monkeypatch.setattr("atlaz.crossrepo.pubsub_service.get_run", lambda thread_id, config: None)
    service = PubSubLinkService(lambda cypher, params: [])

    with pytest.raises(ValueError, match="unknown-thread"):
        service.scan("unknown-thread")


def test_scan_attributes_signal_to_owning_service_and_normalizes_topic(monkeypatch, tmp_path):
    (tmp_path / "producer.py").write_text('producer.send("OrderCreated", value=payload)\n')

    monkeypatch.setattr(
        "atlaz.crossrepo.pubsub_service.get_run",
        lambda thread_id, config: _FakeRun(repo_id="repo-a", repo_path=str(tmp_path)),
    )

    class _Facts:
        service_files: ClassVar = {"checkout": ["producer.py"]}

    monkeypatch.setattr("atlaz.crossrepo.pubsub_service.fetch_project_facts", lambda runner, thread_id, repo_id: _Facts())

    service = PubSubLinkService(lambda cypher, params: [])
    findings = service.scan("t1")

    assert len(findings) == 1
    f = findings[0]
    assert f.repo_id == "repo-a"
    assert f.service == "checkout"
    assert f.direction == "publish"
    assert f.topic == "ordercreated"  # normalized: lowercased, separators stripped
    assert f.library == "kafka"


def test_scan_drops_signal_with_unattributable_file(monkeypatch, tmp_path):
    (tmp_path / "producer.py").write_text('producer.send("OrderCreated", value=payload)\n')

    monkeypatch.setattr(
        "atlaz.crossrepo.pubsub_service.get_run",
        lambda thread_id, config: _FakeRun(repo_id="repo-a", repo_path=str(tmp_path)),
    )

    class _Facts:
        service_files: ClassVar = {}  # producer.py isn't attributed to any known component

    monkeypatch.setattr("atlaz.crossrepo.pubsub_service.fetch_project_facts", lambda runner, thread_id, repo_id: _Facts())

    service = PubSubLinkService(lambda cypher, params: [])

    assert service.scan("t1") == []


def test_write_persists_edge_with_repo_id_qualified_match_and_no_repo_id_on_event(monkeypatch):
    monkeypatch.setattr("atlaz.crossrepo.pubsub_service.record_evidence", lambda records, config: None)
    queries = []

    def runner(cypher, params):
        queries.append((cypher, params))
        return []

    finding = PubSubFinding(
        repo_id="repo-a",
        service="checkout",
        direction="publish",
        topic="ordercreated",
        library="kafka",
        confidence=0.7,
        evidence=Evidence(file="producer.py", line=1),
    )

    service = PubSubLinkService(runner)
    written = service.write([finding])

    assert written == 1
    cypher, params = queries[0]
    assert "repo_id: $repo_id" in cypher
    assert "MERGE (e:Event {event_id: $event_id})" in cypher
    assert "MERGE (s)-[r:PUBLISHES]->(e)" in cypher
    assert params["service"] == "checkout"
    assert params["repo_id"] == "repo-a"
    assert params["event_id"] == "ordercreated"
    assert "repo_id" not in params["event_properties"]
    assert params["edge_properties"]["status"] == "unconfirmed"
    assert params["edge_properties"]["library"] == "kafka"


def test_write_uses_consumes_edge_for_consume_direction(monkeypatch):
    monkeypatch.setattr("atlaz.crossrepo.pubsub_service.record_evidence", lambda records, config: None)
    queries = []

    def runner(cypher, params):
        queries.append((cypher, params))
        return []

    finding = PubSubFinding(
        repo_id="repo-b",
        service="fulfillment",
        direction="consume",
        topic="ordercreated",
        library="kafka",
        confidence=0.7,
        evidence=Evidence(file="consumer.py", line=1),
    )

    service = PubSubLinkService(runner)
    service.write([finding])

    cypher, _ = queries[0]
    assert "MERGE (s)-[r:CONSUMES]->(e)" in cypher

from dataclasses import dataclass

import pytest

from atlaz.docgen.service import DocumentationService
from atlaz.llm.client import MockLLMClient


@dataclass
class _FakeRun:
    repo_id: str
    repo_path: str = "/tmp/somewhere"


def _empty_runner(cypher, params):
    return []


def test_generate_raises_for_unknown_thread(monkeypatch):
    monkeypatch.setattr("atlaz.docgen.service.get_run", lambda thread_id, config: None)
    service = DocumentationService(MockLLMClient(), _empty_runner)

    with pytest.raises(ValueError, match="unknown-thread"):
        service.generate("unknown-thread")


def test_generate_scopes_facts_to_the_runs_repo_id(monkeypatch):
    monkeypatch.setattr("atlaz.docgen.service.get_run", lambda thread_id, config: _FakeRun(repo_id="repo-xyz"))
    seen = []

    def runner(cypher, params):
        seen.append(params.get("repo_id"))
        return []

    service = DocumentationService(MockLLMClient(), runner)
    facts, hld, lld = service.generate("t1")

    assert seen and all(r == "repo-xyz" for r in seen)
    assert facts.repository.repo_id == "repo-xyz"
    assert "# High-Level Design" in hld
    assert "# Low-Level Design" in lld


def test_run_writes_output_when_save_true(monkeypatch, tmp_path):
    monkeypatch.setattr("atlaz.docgen.service.get_run", lambda thread_id, config: _FakeRun(repo_id="repo-xyz"))
    service = DocumentationService(MockLLMClient(), _empty_runner, output_root=tmp_path)

    result = service.run("t1", "proj-1", save=True)

    assert result.output_dir is not None
    assert (result.output_dir / "HLD.md").exists()
    assert (result.output_dir / "LLD.md").exists()


def test_run_skips_writing_when_save_false(monkeypatch, tmp_path):
    monkeypatch.setattr("atlaz.docgen.service.get_run", lambda thread_id, config: _FakeRun(repo_id="repo-xyz"))
    service = DocumentationService(MockLLMClient(), _empty_runner, output_root=tmp_path)

    result = service.run("t1", "proj-1", save=False)

    assert result.output_dir is None
    assert list(tmp_path.iterdir()) == []

import pytest

from atlaz.enhancement.models import FileModification, RetrievedGuideline
from atlaz.enhancement.service import EnhancementService


class _FakeRun:
    def __init__(self, repo_path: str):
        self.repo_path = repo_path


class _StubModifier:
    def __init__(self):
        self.calls = []

    def run(self, file_path, current_content, task_description, guidelines=None):
        self.calls.append((file_path, task_description, guidelines))
        return FileModification(
            file_path=file_path, original_content=current_content,
            modified_content=current_content + "\n# modified", task_description=task_description,
        )


class _StubGuidelineAgent:
    def query(self, text, category=None, limit=3):
        return [RetrievedGuideline(title="G", category="c", content="follow this", score=0.9)]


def _service(monkeypatch, repo_path: str, impact_files, guideline_agent=None):
    monkeypatch.setattr("atlaz.enhancement.service.get_run", lambda thread_id, config=None: _FakeRun(repo_path))

    class _StubImpactAgent:
        def run(self, enhancement_request, limit=15):
            from atlaz.enhancement.models import ImpactAnalysisResult

            return ImpactAnalysisResult(matched_nodes=["n1"], files=impact_files)

    return EnhancementService(_StubImpactAgent(), _StubModifier(), guideline_agent)


def test_resolve_repo_path_raises_for_unknown_thread(monkeypatch):
    monkeypatch.setattr("atlaz.enhancement.service.get_run", lambda thread_id, config=None: None)
    service = EnhancementService(None, None)

    with pytest.raises(ValueError, match="unknown-thread"):
        service.resolve_repo_path("unknown-thread")


def test_generate_reads_files_from_repo_path_and_skips_missing(monkeypatch, tmp_path):
    (tmp_path / "present.py").write_text("print('hi')\n")
    from atlaz.enhancement.models import ImpactedFile

    service = _service(
        monkeypatch, str(tmp_path),
        [ImpactedFile(file_path="present.py", reason="r"), ImpactedFile(file_path="missing.py", reason="r")],
    )

    repo_path, impact, guidelines = service.analyze("thread-1", "add feature")
    modifications, skipped = service.generate(repo_path, "add feature", impact, guidelines)

    assert repo_path == str(tmp_path)
    assert skipped == ["missing.py"]
    assert len(modifications) == 1
    assert modifications[0].file_path == "present.py"
    assert modifications[0].modified_content == "print('hi')\n\n# modified"


def test_analyze_queries_guideline_agent_when_configured(monkeypatch, tmp_path):
    from atlaz.enhancement.models import ImpactedFile

    service = _service(monkeypatch, str(tmp_path), [ImpactedFile(file_path="a.py", reason="r")], _StubGuidelineAgent())

    _, _, guidelines = service.analyze("thread-1", "add feature")

    assert len(guidelines) == 1
    assert guidelines[0].title == "G"


def test_run_end_to_end_and_save(monkeypatch, tmp_path):
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo" / "a.py").write_text("x = 1\n")
    from atlaz.enhancement.models import ImpactedFile

    service = _service(monkeypatch, str(tmp_path / "repo"), [ImpactedFile(file_path="a.py", reason="matches")])
    service.output_root = tmp_path / "outputs"

    result = service.run("thread-1", "add feature")
    assert len(result.modifications) == 1

    output_dir = service.save(result, "add feature")
    assert (output_dir / "files" / "a.py").exists()
    assert result.output_dir == output_dir

import json

from atlaz.enhancement.models import FileModification, ImpactAnalysisResult, ImpactedFile, RetrievedGuideline
from atlaz.enhancement.output_writer import write_modifications


def test_write_modifications_creates_files_manifest_and_report(tmp_path):
    impact = ImpactAnalysisResult(
        matched_nodes=["cfg::rate_limit"],
        files=[ImpactedFile(file_path="checkout/service.py", reason="matches request", matched_node_labels=["BusinessRule"])],
    )
    guidelines = [RetrievedGuideline(title="Naming", category="coding_standards", content="use snake_case", score=0.5)]
    modifications = [
        FileModification(
            file_path="checkout/service.py",
            original_content="def checkout():\n    pass\n",
            modified_content="def checkout():\n    check_rate_limit()\n",
            task_description="add rate limiting",
        )
    ]

    output_dir = write_modifications(tmp_path, "thread-123", "add rate limiting", impact, guidelines, modifications)

    assert output_dir.exists()
    assert (output_dir / "files" / "checkout" / "service.py").read_text() == "def checkout():\n    check_rate_limit()\n"

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["thread_id"] == "thread-123"
    assert manifest["modified_files"] == ["checkout/service.py"]
    assert manifest["impacted_files"][0]["file_path"] == "checkout/service.py"

    report = (output_dir / "report.md").read_text()
    assert "checkout/service.py" in report
    assert "check_rate_limit" in report
    assert "Naming" in report


def test_write_modifications_never_touches_the_source_repo(tmp_path):
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    original_file = repo_dir / "service.py"
    original_file.write_text("def checkout():\n    pass\n")

    output_root = tmp_path / "outputs"
    impact = ImpactAnalysisResult(matched_nodes=[], files=[ImpactedFile(file_path="service.py", reason="r")])
    modifications = [
        FileModification(
            file_path="service.py",
            original_content="def checkout():\n    pass\n",
            modified_content="def checkout():\n    return True\n",
            task_description="t",
        )
    ]

    write_modifications(output_root, "thread-1", "req", impact, [], modifications)

    assert original_file.read_text() == "def checkout():\n    pass\n"

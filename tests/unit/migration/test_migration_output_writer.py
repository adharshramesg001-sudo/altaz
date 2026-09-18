import json

from atlaz.enhancement.models import FileValidation
from atlaz.migration.models import GeneratedFile, GeneratedUnit, MigrationPlan, MigrationTask, MigrationUnit
from atlaz.migration.output_writer import write_migration


def test_write_migration_creates_files_manifest_and_report(tmp_path):
    units = [MigrationUnit(unit_id="cap-1", unit_type="capability", name="Billing", description="d")]
    plan = MigrationPlan(summary="Migrate to microservices.", tasks=[MigrationTask(unit_id="cap-1", title="T", description="D")])
    generated_units = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="D",
                       files=[GeneratedFile(file_path="billing/main.py", content="def app(): ...\n")])
    ]
    validations = [FileValidation(file_path="billing/main.py", syntax_valid=True, security_issues=["possible leak"])]

    output_dir = write_migration(tmp_path, "thread-1", "migrate to FastAPI", units, plan, generated_units, validations)

    assert (output_dir / "files" / "billing" / "main.py").read_text() == "def app(): ...\n"

    manifest = json.loads((output_dir / "manifest.json").read_text())
    assert manifest["thread_id"] == "thread-1"
    assert manifest["generated_files"] == ["billing/main.py"]
    assert manifest["plan_summary"] == "Migrate to microservices."

    report = (output_dir / "report.md").read_text()
    assert "Migrate to microservices." in report
    assert "billing/main.py" in report
    assert "flagged on review" in report
    assert "possible leak" in report


def test_write_migration_never_touches_the_source_repo(tmp_path):
    repo_dir = tmp_path / "source_repo"
    repo_dir.mkdir()
    original_file = repo_dir / "billing" / "main.py"
    original_file.parent.mkdir()
    original_file.write_text("legacy code\n")

    output_root = tmp_path / "outputs"
    units = [MigrationUnit(unit_id="cap-1", unit_type="capability", name="Billing", description="d")]
    generated_units = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="t",
                       files=[GeneratedFile(file_path="billing/main.py", content="new code\n")])
    ]

    write_migration(output_root, "thread-1", "migrate", units, MigrationPlan(summary="s"), generated_units)

    assert original_file.read_text() == "legacy code\n"

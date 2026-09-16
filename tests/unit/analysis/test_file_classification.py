from atlaz.analysis.file_classification import classify_file, classify_inventory
from atlaz.ingestion.models import FileRecord, RepoInventory


def _inventory(**overrides) -> RepoInventory:
    kwargs = {"repo_id": "r", "repo_root": "/tmp/r", "commit_sha": None}
    kwargs.update(overrides)
    return RepoInventory(**kwargs)


def test_test_file_classified_as_test_even_if_it_has_a_language():
    record = FileRecord(path="tests/test_app.py", language="python", size=1, last_modified=0.0)
    assert classify_file(record, _inventory()) == "test"


def test_infra_filenames_classified_as_infra():
    record = FileRecord(path="Dockerfile", language=None, size=1, last_modified=0.0)
    assert classify_file(record, _inventory()) == "infra"


def test_readme_classified_as_docs():
    record = FileRecord(path="README.md", language=None, size=1, last_modified=0.0)
    inventory = _inventory(readme_paths=["README.md"])
    assert classify_file(record, inventory) == "docs"


def test_manifest_path_classified_as_build():
    record = FileRecord(path="pyproject.toml", language=None, size=1, last_modified=0.0)
    inventory = _inventory(manifest_paths=["pyproject.toml"])
    assert classify_file(record, inventory) == "build"


def test_config_path_classified_as_config():
    record = FileRecord(path="settings.yaml", language=None, size=1, last_modified=0.0)
    inventory = _inventory(config_paths=["settings.yaml"])
    assert classify_file(record, inventory) == "config"


def test_language_tagged_file_classified_as_source():
    record = FileRecord(path="app.py", language="python", size=1, last_modified=0.0)
    assert classify_file(record, _inventory()) == "source"


def test_unclassifiable_file_is_unknown_not_dropped():
    record = FileRecord(path="data.bin", language=None, size=1, last_modified=0.0)
    assert classify_file(record, _inventory()) == "unknown"


def test_classify_inventory_covers_every_file():
    files = [FileRecord(path="a.py", language="python", size=1, last_modified=0.0), FileRecord(path="b.bin", language=None, size=1, last_modified=0.0)]
    inventory = _inventory(files=files)
    result = classify_inventory(inventory)
    assert result == {"a.py": "source", "b.bin": "unknown"}

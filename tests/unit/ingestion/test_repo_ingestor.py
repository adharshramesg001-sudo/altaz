from pathlib import Path

from atlaz.ingestion.repo_ingestor import RepoIngestor


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_ingest_tags_languages_and_finds_manifests(tmp_path: Path):
    _write(tmp_path / "README.md", "# Demo")
    _write(tmp_path / "pyproject.toml", "[project]\nname='demo'")
    _write(tmp_path / "src" / "app.py", "def main():\n    pass\n")
    _write(tmp_path / "web" / "index.tsx", "export const x = 1;")
    _write(tmp_path / "config" / "settings.yaml", "debug: true")
    _write(tmp_path / "node_modules" / "pkg" / "index.js", "module.exports = {}")

    inventory = RepoIngestor().ingest(str(tmp_path))

    paths = {f.path for f in inventory.files}
    assert "src/app.py" in paths
    assert "web/index.tsx" in paths
    assert not any(p.startswith("node_modules/") for p in paths), "node_modules must be excluded"

    langs = {f.path: f.language for f in inventory.files}
    assert langs["src/app.py"] == "python"
    assert langs["web/index.tsx"] == "typescript"

    assert "README.md" in inventory.readme_paths
    assert "pyproject.toml" in inventory.manifest_paths
    assert "config/settings.yaml" in inventory.config_paths


def test_ingest_detects_shebang_language_for_extensionless_scripts(tmp_path: Path):
    script = tmp_path / "bin" / "run"
    _write(script, "#!/usr/bin/env python3\nprint('hi')\n")

    inventory = RepoIngestor().ingest(str(tmp_path))

    record = next(f for f in inventory.files if f.path == "bin/run")
    assert record.language == "python"


def test_ingest_raises_for_missing_directory(tmp_path: Path):
    import pytest

    with pytest.raises(NotADirectoryError):
        RepoIngestor().ingest(str(tmp_path / "does-not-exist"))

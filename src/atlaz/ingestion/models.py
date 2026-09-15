"""Data shapes produced by the ingestion layer (LLD Section 3)."""

from __future__ import annotations

from dataclasses import dataclass, field

MANIFEST_FILENAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "cargo.toml",
    "gemfile",
    "composer.json",
}
MANIFEST_SUFFIXES = {".csproj"}

CONFIG_SUFFIXES = {".env", ".yml", ".yaml", ".json", ".toml", ".ini", ".cfg"}


@dataclass(slots=True)
class FileRecord:
    path: str  # relative to repo root, POSIX separators
    language: str | None
    size: int
    last_modified: float


@dataclass(slots=True)
class RepoInventory:
    """The single object passed into every extraction agent.

    No agent re-walks the filesystem independently -- this is what keeps
    file-level evidence citations consistent across every domain.
    """

    repo_id: str
    repo_root: str
    commit_sha: str | None
    files: list[FileRecord] = field(default_factory=list)
    readme_paths: list[str] = field(default_factory=list)
    config_paths: list[str] = field(default_factory=list)
    manifest_paths: list[str] = field(default_factory=list)

    def files_by_language(self) -> dict[str, list[FileRecord]]:
        grouped: dict[str, list[FileRecord]] = {}
        for f in self.files:
            grouped.setdefault(f.language or "unknown", []).append(f)
        return grouped

    def abs_path(self, relative_path: str) -> str:
        import os

        return os.path.join(self.repo_root, relative_path)

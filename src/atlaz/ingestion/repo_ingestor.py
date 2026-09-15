"""RepoIngestor (LLD Section 3).

Take a repository path, produce a normalized file inventory tagged by
language, and route each file to the correct parser downstream. Runs once
per pipeline execution.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from posixpath import join as posix_join

from atlaz.ingestion.extension_map import language_for_extension, language_from_shebang
from atlaz.ingestion.models import (
    CONFIG_SUFFIXES,
    MANIFEST_FILENAMES,
    MANIFEST_SUFFIXES,
    FileRecord,
    RepoInventory,
)

DEFAULT_IGNORE_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".venv",
        "venv",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        "site-packages",
        "egg-info",
    }
)

_SHEBANG_SNIFF_BYTES = 128


class RepoIngestor:
    def __init__(self, ignore_dirs: frozenset[str] | None = None) -> None:
        self.ignore_dirs = ignore_dirs or DEFAULT_IGNORE_DIRS

    def ingest(self, repo_path: str) -> RepoInventory:
        root = Path(repo_path).resolve()
        if not root.is_dir():
            raise NotADirectoryError(f"repo_path does not exist or is not a directory: {root}")

        files: list[FileRecord] = []
        readme_paths: list[str] = []
        config_paths: list[str] = []
        manifest_paths: list[str] = []

        for abs_path in self._walk(root):
            rel_path = self._relative_posix(root, abs_path)
            try:
                stat = abs_path.stat()
            except OSError:
                continue

            language = self._detect_file_language(abs_path)
            files.append(
                FileRecord(path=rel_path, language=language, size=stat.st_size, last_modified=stat.st_mtime)
            )

            name_lower = abs_path.name.lower()
            if name_lower.startswith("readme"):
                readme_paths.append(rel_path)
            if name_lower in MANIFEST_FILENAMES or abs_path.suffix.lower() in MANIFEST_SUFFIXES:
                manifest_paths.append(rel_path)
            elif abs_path.suffix.lower() in CONFIG_SUFFIXES or name_lower.startswith(".env"):
                config_paths.append(rel_path)

        return RepoInventory(
            repo_id=root.name,
            repo_root=str(root),
            commit_sha=self._current_commit_sha(root),
            files=files,
            readme_paths=readme_paths,
            config_paths=config_paths,
            manifest_paths=manifest_paths,
        )

    def _walk(self, root: Path):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in self.ignore_dirs and not d.endswith(".egg-info")]
            for filename in filenames:
                yield Path(dirpath) / filename

    @staticmethod
    def _relative_posix(root: Path, abs_path: Path) -> str:
        rel = abs_path.relative_to(root)
        return posix_join(*rel.parts) if rel.parts else ""

    @staticmethod
    def _detect_file_language(abs_path: Path) -> str | None:
        by_ext = language_for_extension(abs_path.suffix)
        if by_ext:
            return by_ext
        if abs_path.suffix:
            return None
        try:
            with open(abs_path, "rb") as fh:
                head = fh.read(_SHEBANG_SNIFF_BYTES)
            first_line = head.split(b"\n", 1)[0].decode("utf-8", errors="ignore")
        except OSError:
            return None
        return language_from_shebang(first_line)

    @staticmethod
    def _current_commit_sha(root: Path) -> str | None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

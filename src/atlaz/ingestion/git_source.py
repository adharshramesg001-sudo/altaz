"""Resolves an ingestion source -- a local filesystem path or a git
repository URL -- to a local path `RepoIngestor` can walk. Lives in
`ingestion/` (not the webapp) so the CLI/API can grow git-URL support the
same way, not just the Streamlit UI.

A git URL is always shallow-cloned fresh into its own UUID-suffixed
subdirectory under `workspace_root` -- never reused across calls, so a
second ingestion of the same URL always gets the latest commit rather than
silently reading a stale clone.
"""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

_GIT_URL_PATTERN = re.compile(r"^(https?://|git@|ssh://)", re.IGNORECASE)
_CLONE_TIMEOUT_SECONDS = 300


class GitCloneError(RuntimeError):
    pass


def is_git_source(source: str) -> bool:
    source = source.strip()
    return bool(_GIT_URL_PATTERN.match(source)) or source.endswith(".git")


def _slugify(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1]
    name = name.removesuffix(".git")
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")
    return slug or "repo"


def clone_repo(url: str, workspace_root: Path | str) -> str:
    workspace_root = Path(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)
    dest = workspace_root / f"{_slugify(url)}-{uuid.uuid4().hex[:8]}"
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True, capture_output=True, text=True, timeout=_CLONE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise GitCloneError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCloneError(f"Cloning {url} timed out after {_CLONE_TIMEOUT_SECONDS}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise GitCloneError(f"git clone failed: {detail or 'unknown error'}") from exc
    return str(dest)


def resolve_repo_source(source: str, workspace_root: Path | str) -> str:
    """Returns a local directory path. Clones `source` first if it looks
    like a git URL; otherwise validates it as an existing local directory."""
    source = source.strip()
    if not source:
        raise ValueError("A repository path or git URL is required.")
    if is_git_source(source):
        return clone_repo(source, workspace_root)
    path = Path(source).expanduser()
    if not path.is_dir():
        raise ValueError(f"'{source}' is not a directory, and doesn't look like a git URL.")
    return str(path.resolve())

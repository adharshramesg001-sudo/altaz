"""Resolves an ingestion source -- a local filesystem path or a git
repository URL -- to a local path `RepoIngestor` can walk. Lives in
`ingestion/` (not the webapp) so the CLI/API can grow git-URL support the
same way, not just the Streamlit UI.

A git URL is always shallow-cloned fresh into its own UUID-suffixed
subdirectory under `workspace_root` -- never reused across calls, so a
second ingestion of the same URL always gets the latest commit rather than
silently reading a stale clone.

Also tolerates a pasted browser URL (GitHub's `/tree/<branch>/...` or
`/blob/<branch>/...`, GitLab's `/-/tree/...`) by splitting it into a bare
clonable repo URL plus a branch, rather than handing it to `git clone`
as-is and failing with a raw "repository not found".
"""

from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

_GIT_URL_PATTERN = re.compile(r"^(https?://|git@|ssh://)", re.IGNORECASE)
_CLONE_TIMEOUT_SECONDS = 300
_LS_REMOTE_TIMEOUT_SECONDS = 30

# Matches a browser "view this branch/file" URL -- GitHub's
# `.../<owner>/<repo>/tree/<branch>[/<path>]` or `/blob/<branch>/<path>`,
# and GitLab's equivalent `.../<group>/<project>/-/tree/<branch>[/<path>]`.
# These are pages for humans, not a URL `git clone` understands: the ref
# and the repo are smashed into one path with no delimiter, and the ref
# itself may contain '/' (branch names like "claude/some-feature"), so
# which prefix is the branch and which is a subdirectory is ambiguous
# from the URL text alone -- resolved later by asking the remote.
_TREE_OR_BLOB_PATTERN = re.compile(r"^(?P<repo_url>.+?)/(?:tree|blob)/(?P<ref_path>[^?#]+?)/?$", re.IGNORECASE)


class GitCloneError(RuntimeError):
    pass


def _split_web_view_url(url: str) -> tuple[str, str | None]:
    """Splits a git-web-UI browsing URL into a bare, clonable repo URL and
    the ref/path fragment after `/tree/` or `/blob/`. Returns `(url, None)`
    unchanged if `url` doesn't look like one of these pages."""
    match = _TREE_OR_BLOB_PATTERN.match(url.strip())
    if not match:
        return url, None
    repo_url = match.group("repo_url").removesuffix("/-")  # GitLab's "-/tree/..." marker
    return repo_url, match.group("ref_path")


def _resolve_branch(repo_url: str, ref_path: str) -> str:
    """`ref_path` came from a `/tree/` or `/blob/` URL and may itself be a
    branch name containing '/', or a branch followed by a subdirectory/file
    path -- the URL alone can't tell which. Asks the remote for its actual
    branch names and picks the longest one that's a prefix of `ref_path`."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--heads", repo_url],
            check=True, capture_output=True, text=True, timeout=_LS_REMOTE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise GitCloneError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCloneError(f"Listing branches for {repo_url} timed out after {_LS_REMOTE_TIMEOUT_SECONDS}s") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise GitCloneError(
            f"Couldn't reach {repo_url!r} to resolve its branch -- this looked like a branch/file "
            f"link ({ref_path!r}), not a plain repo URL. {detail or 'unknown error'}"
        ) from exc

    branches = [line.split("refs/heads/", 1)[-1] for line in result.stdout.splitlines() if "refs/heads/" in line]
    matches = sorted(
        (b for b in branches if ref_path == b or ref_path.startswith(b + "/")), key=len, reverse=True
    )
    if not matches:
        raise GitCloneError(
            f"'{ref_path}' from that link doesn't match any branch in {repo_url} "
            f"(checked {len(branches)} branch(es)) -- did you mean to paste the plain repo URL "
            f"(https://.../{{owner}}/{{repo}}) instead of a branch/file link?"
        )
    return matches[0]


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

    repo_url, ref_path = _split_web_view_url(url)
    branch = _resolve_branch(repo_url, ref_path) if ref_path else None

    dest = workspace_root / f"{_slugify(repo_url)}-{uuid.uuid4().hex[:8]}"
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [repo_url, str(dest)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=_CLONE_TIMEOUT_SECONDS)
    except FileNotFoundError as exc:
        raise GitCloneError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitCloneError(f"Cloning {repo_url} timed out after {_CLONE_TIMEOUT_SECONDS}s") from exc
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

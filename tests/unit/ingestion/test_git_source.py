import subprocess

import pytest

from atlaz.ingestion.git_source import (
    GitCloneError,
    _resolve_branch,
    _split_web_view_url,
    clone_repo,
    is_git_source,
    resolve_repo_source,
)


@pytest.mark.parametrize(
    "source",
    [
        "https://github.com/org/repo",
        "https://github.com/org/repo.git",
        "git@github.com:org/repo.git",
        "ssh://git@example.com/org/repo.git",
        "some/local/path.git",  # no scheme, but .git suffix is still a strong signal
    ],
)
def test_recognizes_git_sources(source):
    assert is_git_source(source) is True


@pytest.mark.parametrize("source", ["/abs/local/path", "relative/path", "./here", "~/projects/thing"])
def test_recognizes_local_paths(source):
    assert is_git_source(source) is False


def test_resolve_repo_source_rejects_empty_input():
    with pytest.raises(ValueError, match="required"):
        resolve_repo_source("   ", "/tmp/workspaces")


def test_resolve_repo_source_rejects_nonexistent_local_path(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="not a directory"):
        resolve_repo_source(str(missing), tmp_path / "workspaces")


def test_resolve_repo_source_accepts_existing_local_directory(tmp_path):
    repo_dir = tmp_path / "myrepo"
    repo_dir.mkdir()
    resolved = resolve_repo_source(str(repo_dir), tmp_path / "workspaces")
    assert resolved == str(repo_dir.resolve())


def test_clone_repo_wraps_missing_git_binary(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GitCloneError, match="not installed"):
        clone_repo("https://example.com/org/repo.git", tmp_path)


def test_clone_repo_wraps_failed_clone(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(128, ["git", "clone"], output="", stderr="fatal: repository not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GitCloneError, match="repository not found"):
        clone_repo("https://example.com/org/does-not-exist.git", tmp_path)


@pytest.mark.parametrize(
    "url,expected_repo,expected_ref",
    [
        ("https://github.com/org/repo", "https://github.com/org/repo", None),
        ("https://github.com/org/repo/tree/main", "https://github.com/org/repo", "main"),
        ("https://github.com/org/repo/tree/main/", "https://github.com/org/repo", "main"),
        (
            "https://github.com/org/repo/tree/claude/some-feature",
            "https://github.com/org/repo",
            "claude/some-feature",
        ),
        (
            "https://github.com/org/repo/blob/main/src/app.py",
            "https://github.com/org/repo",
            "main/src/app.py",
        ),
        (
            "https://gitlab.com/group/proj/-/tree/main/src",
            "https://gitlab.com/group/proj",
            "main/src",
        ),
    ],
)
def test_split_web_view_url(url, expected_repo, expected_ref):
    repo_url, ref_path = _split_web_view_url(url)
    assert repo_url == expected_repo
    assert ref_path == expected_ref


def test_resolve_branch_picks_longest_matching_prefix(monkeypatch):
    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["git", "ls-remote", "--heads"]

        class _Result:
            stdout = (
                "abc123\trefs/heads/claude\n"
                "def456\trefs/heads/claude/some-feature\n"
                "ghi789\trefs/heads/main\n"
            )

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    branch = _resolve_branch("https://github.com/org/repo", "claude/some-feature")
    assert branch == "claude/some-feature"


def test_resolve_branch_raises_when_no_branch_matches(monkeypatch):
    def fake_run(cmd, **kwargs):
        class _Result:
            stdout = "ghi789\trefs/heads/main\n"

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(GitCloneError, match="doesn't match any branch"):
        _resolve_branch("https://github.com/org/repo", "claude/some-feature")


def test_clone_repo_resolves_tree_url_to_branch_flag(monkeypatch, tmp_path):
    seen_cmds = []

    def fake_run(cmd, **kwargs):
        seen_cmds.append(cmd)

        class _Result:
            stdout = "def456\trefs/heads/claude/some-feature\n"

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    clone_repo("https://github.com/org/repo/tree/claude/some-feature", tmp_path)

    ls_remote_cmd, clone_cmd = seen_cmds
    assert ls_remote_cmd[:3] == ["git", "ls-remote", "--heads"]
    assert ls_remote_cmd[3] == "https://github.com/org/repo"
    assert clone_cmd[:2] == ["git", "clone"]
    assert "--branch" in clone_cmd
    assert clone_cmd[clone_cmd.index("--branch") + 1] == "claude/some-feature"
    assert "https://github.com/org/repo" in clone_cmd


def test_clone_repo_destination_is_slugified_and_unique(monkeypatch, tmp_path):
    seen_dest = []

    def fake_run(cmd, **kwargs):
        seen_dest.append(cmd[-1])

        class _Result:
            pass

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)
    dest1 = clone_repo("https://github.com/org/My Repo!!.git", tmp_path)
    dest2 = clone_repo("https://github.com/org/My Repo!!.git", tmp_path)

    assert "My-Repo" in dest1
    assert dest1 != dest2  # never reused -- always a fresh clone

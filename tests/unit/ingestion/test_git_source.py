import subprocess

import pytest

from atlaz.ingestion.git_source import GitCloneError, clone_repo, is_git_source, resolve_repo_source


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

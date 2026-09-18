from atlaz.migration.infra_files import fetch_files_by_classification


def test_returns_paths_from_query_runner():
    calls = []

    def query_runner(cypher, params):
        calls.append((cypher, params))
        return [{"path": "Dockerfile"}, {"path": "requirements.txt"}]

    paths = fetch_files_by_classification(query_runner, "repo-1", ["infra", "build"])

    assert paths == ["Dockerfile", "requirements.txt"]
    assert calls[0][1] == {"repo_id": "repo-1", "classifications": ["infra", "build"]}


def test_skips_rows_with_no_path():
    paths = fetch_files_by_classification(lambda c, p: [{"path": None}, {"path": "a.py"}], "repo-1", ["source"])

    assert paths == ["a.py"]


def test_empty_result_returns_empty_list():
    paths = fetch_files_by_classification(lambda c, p: [], "repo-1", ["infra"])

    assert paths == []

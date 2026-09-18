from atlaz.migration.dependency_scanner import scan_dependencies


def test_parses_requirements_txt(tmp_path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\nflask>=2.0\n# a comment\n\nnumpy\n")

    deps = scan_dependencies(str(tmp_path), ["requirements.txt"])

    by_name = {d.name: d for d in deps}
    assert by_name["requests"].version == "2.31.0"
    assert by_name["requests"].ecosystem == "pypi"
    assert by_name["flask"].version == "2.0"
    assert by_name["numpy"].version == ""


def test_parses_pyproject_toml_pep621(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\ndependencies = ["requests>=2.28", "click==8.1.0"]\n'
    )

    deps = scan_dependencies(str(tmp_path), ["pyproject.toml"])

    by_name = {d.name: d for d in deps}
    assert by_name["requests"].version == "2.28"
    assert by_name["click"].version == "8.1.0"
    assert all(d.ecosystem == "pypi" for d in deps)


def test_parses_pyproject_toml_poetry_and_skips_python_itself(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.poetry.dependencies]\npython = "^3.11"\nrequests = "^2.31.0"\n'
        'fastapi = {version = "^0.100.0", extras = ["all"]}\n'
    )

    deps = scan_dependencies(str(tmp_path), ["pyproject.toml"])

    names = {d.name for d in deps}
    assert "python" not in names
    by_name = {d.name: d for d in deps}
    assert by_name["requests"].version == "2.31.0"
    assert by_name["fastapi"].version == "0.100.0"


def test_parses_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"dependencies": {"axios": "^1.4.0"}, "devDependencies": {"jest": "~29.0.0"}}'
    )

    deps = scan_dependencies(str(tmp_path), ["package.json"])

    by_name = {d.name: d for d in deps}
    assert by_name["axios"].version == "1.4.0"
    assert by_name["axios"].ecosystem == "npm"
    assert by_name["jest"].version == "29.0.0"


def test_unrecognized_manifest_is_skipped(tmp_path):
    (tmp_path / "go.mod").write_text("module demo\ngo 1.21\n")

    deps = scan_dependencies(str(tmp_path), ["go.mod"])

    assert deps == []


def test_missing_file_is_skipped_not_raised(tmp_path):
    deps = scan_dependencies(str(tmp_path), ["requirements.txt"])

    assert deps == []


def test_malformed_json_and_toml_do_not_raise(tmp_path):
    (tmp_path / "package.json").write_text("{not valid json")
    (tmp_path / "pyproject.toml").write_text("not = [valid toml")

    deps = scan_dependencies(str(tmp_path), ["package.json", "pyproject.toml"])

    assert deps == []

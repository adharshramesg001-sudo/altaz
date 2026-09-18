from types import SimpleNamespace

import pytest

from atlaz.migration.models import (
    Dependency,
    DependencyMapping,
    GeneratedFile,
    GeneratedUnit,
    MigrationPlan,
    MigrationTask,
    MigrationUnit,
)
from atlaz.migration.service import MigrationService


class _FakeRun:
    def __init__(self, repo_id: str, repo_path: str = "/repo"):
        self.repo_id = repo_id
        self.repo_path = repo_path


class _StubPlanningAgent:
    def __init__(self, plan: MigrationPlan):
        self.plan = plan
        self.calls = []

    def run(self, migration_request, units, current_language=""):
        self.calls.append((migration_request, units, current_language))
        return self.plan


class _StubGenerationAgent:
    def __init__(self):
        self.calls = []

    def run(self, migration_request, unit, task_description, guidelines=None):
        self.calls.append((migration_request, unit, task_description, guidelines))
        return GeneratedUnit(
            unit_id=unit.unit_id, unit_type=unit.unit_type, name=unit.name, task_description=task_description,
            files=[GeneratedFile(file_path=f"{unit.unit_id}/main.py", content="x = 1\n")],
        )


class _StubGuidelineAgent:
    def query(self, text, category=None, limit=3):
        from atlaz.enhancement.models import RetrievedGuideline

        return [RetrievedGuideline(title="G", category="c", content="follow this", score=0.9)]


def _units() -> list[MigrationUnit]:
    return [
        MigrationUnit(unit_id="cap-1", unit_type="capability", name="Billing", description="d1"),
        MigrationUnit(unit_id="cap-2", unit_type="capability", name="Auth", description="d2"),
    ]


def _service(monkeypatch, repo_id: str, units, plan, guideline_agent=None) -> MigrationService:
    monkeypatch.setattr("atlaz.migration.service.get_run", lambda thread_id, config=None: _FakeRun(repo_id))
    fake_facts = SimpleNamespace(repository=SimpleNamespace(primary_languages=["python"]))
    monkeypatch.setattr("atlaz.migration.service.fetch_project_facts", lambda query_runner, thread_id, repo_id: fake_facts)
    monkeypatch.setattr("atlaz.migration.service.build_migration_units", lambda facts, repo_path=None: units)

    return MigrationService(
        query_runner=lambda cypher, params: [], planning_agent=_StubPlanningAgent(plan),
        generation_agent=_StubGenerationAgent(), guideline_agent=guideline_agent,
    )


def test_resolve_repo_id_raises_for_unknown_thread(monkeypatch):
    monkeypatch.setattr("atlaz.migration.service.get_run", lambda thread_id, config=None: None)
    service = MigrationService(query_runner=lambda c, p: [], planning_agent=None, generation_agent=None)

    with pytest.raises(ValueError, match="unknown-thread"):
        service.resolve_repo_id("unknown-thread")


def test_generate_uses_plan_task_description_when_a_task_matches_the_unit(monkeypatch):
    plan = MigrationPlan(summary="s", tasks=[MigrationTask(unit_id="cap-1", title="T", description="Do the thing")])
    service = _service(monkeypatch, "repo-1", _units(), plan)

    service.generate("migrate", _units(), plan, [])

    gen_agent: _StubGenerationAgent = service.generation_agent
    assert gen_agent.calls[0][2] == "Do the thing"
    assert "Migrate this capability" in gen_agent.calls[1][2]  # cap-2 has no matching task -- generic fallback


def test_validate_builds_file_modifications_from_generated_files(monkeypatch):
    service = _service(monkeypatch, "repo-1", _units(), MigrationPlan(summary="s"))
    generated = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="t",
                       files=[GeneratedFile(file_path="a.py", content="x = 1\n")])
    ]

    validations = service.validate(generated)

    assert len(validations) == 1
    assert validations[0].file_path == "a.py"
    assert validations[0].syntax_valid


def test_validate_flags_dropped_response_fields_when_units_are_passed(monkeypatch):
    service = _service(monkeypatch, "repo-1", _units(), MigrationPlan(summary="s"))
    units_with_known_fields = [
        MigrationUnit(unit_id="cap-1", unit_type="capability", name="Billing", description="d1",
                      known_response_fields=["status", "service"])
    ]
    generated = [
        GeneratedUnit(unit_id="cap-1", unit_type="capability", name="Billing", task_description="t",
                      files=[GeneratedFile(file_path="Health.java", content='return "OK";')])
    ]

    validations = service.validate(generated, units_with_known_fields)

    assert validations[0].warnings
    assert "status" in validations[0].warnings[0]
    assert validations[0].syntax_valid


def test_run_end_to_end_and_save(monkeypatch, tmp_path):
    plan = MigrationPlan(summary="Migrate everything.", tasks=[])
    service = _service(monkeypatch, "repo-1", _units(), plan, guideline_agent=_StubGuidelineAgent())
    service.output_root = tmp_path / "outputs"

    result = service.run("thread-1", "migrate to FastAPI microservices")

    assert result.repo_id == "repo-1"
    assert len(result.units) == 2
    assert len(result.generated_units) == 2
    assert len(result.guidelines) == 1
    assert len(result.validations) == 2  # one generated file per unit

    output_dir = service.save(result, "migrate to FastAPI microservices")
    assert (output_dir / "files" / "cap-1" / "main.py").exists()
    assert (output_dir / "manifest.json").exists()
    assert result.output_dir == output_dir


class _StubInfraAgent:
    def __init__(self):
        self.calls = []

    def run(self, migration_request, plan_summary, current_files, generated_unit_file_paths, dependency_mappings=None, guidelines=None):
        self.calls.append((migration_request, plan_summary, current_files, generated_unit_file_paths, dependency_mappings))
        return GeneratedUnit(
            unit_id="infra", unit_type="infra", name="Infrastructure & build", task_description="t",
            files=[GeneratedFile(file_path="Dockerfile", content="FROM python:3.12\n")],
        )


def test_generate_runs_infra_unit_last_and_passes_other_units_file_paths(tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.9\n")
    infra_agent = _StubInfraAgent()
    service = MigrationService(
        query_runner=lambda c, p: [], planning_agent=None, generation_agent=_StubGenerationAgent(),
        infra_generation_agent=infra_agent,
    )
    units = [*_units(), MigrationUnit(unit_id="infra", unit_type="infra", name="Infrastructure & build",
                                        description="d", file_paths=["Dockerfile"])]
    plan = MigrationPlan(summary="s")

    generated = service.generate("migrate", units, plan, [], repo_path=str(tmp_path))

    assert [g.unit_type for g in generated] == ["capability", "capability", "infra"]
    call = infra_agent.calls[0]
    assert call[2] == {"Dockerfile": "FROM python:3.9\n"}
    assert call[3] == {"Billing": ["cap-1/main.py"], "Auth": ["cap-2/main.py"]}


def test_generate_skips_infra_when_no_infra_generation_agent_configured(tmp_path):
    service = MigrationService(
        query_runner=lambda c, p: [], planning_agent=None, generation_agent=_StubGenerationAgent(),
    )
    units = [MigrationUnit(unit_id="infra", unit_type="infra", name="Infra", description="d", file_paths=["Dockerfile"])]

    generated = service.generate("migrate", units, MigrationPlan(summary="s"), [], repo_path=str(tmp_path))

    assert generated == []


class _StubDependencyMappingAgent:
    def __init__(self, mappings):
        self.mappings = mappings
        self.calls = []

    def run(self, migration_request, dependencies, target_language, same_language):
        self.calls.append((migration_request, dependencies, target_language, same_language))
        return self.mappings


class _StubRegistryClient:
    def get_json(self, url):
        return {"info": {"version": "9.9.9"}} if "pypi" in url else None


def test_gather_dependencies_scans_manifest_files_from_the_graph(tmp_path):
    (tmp_path / "requirements.txt").write_text("flask==2.0\n")
    service = MigrationService(
        query_runner=lambda cypher, params: [{"path": "requirements.txt"}], planning_agent=None, generation_agent=None,
    )

    deps = service.gather_dependencies("repo-1", str(tmp_path))

    assert len(deps) == 1
    assert deps[0].name == "flask"


def test_propose_dependency_mappings_returns_empty_without_dependencies_or_agent():
    service = MigrationService(query_runner=lambda c, p: [], planning_agent=None, generation_agent=None)

    assert service.propose_dependency_mappings("migrate", [], MigrationPlan(summary="s")) == []
    assert service.propose_dependency_mappings(
        "migrate", [Dependency(name="flask", version="2.0", ecosystem="pypi", manifest_path="requirements.txt")],
        MigrationPlan(summary="s"),
    ) == []  # no dependency_mapping_agent configured


def test_propose_dependency_mappings_delegates_to_agent():
    mapping = DependencyMapping(
        current_name="flask", current_version="2.0", current_ecosystem="pypi",
        target_name="fastapi", target_version="", target_ecosystem="pypi", justification="j",
    )
    agent = _StubDependencyMappingAgent([mapping])
    service = MigrationService(
        query_runner=lambda c, p: [], planning_agent=None, generation_agent=None, dependency_mapping_agent=agent,
    )
    deps = [Dependency(name="flask", version="2.0", ecosystem="pypi", manifest_path="requirements.txt")]
    plan = MigrationPlan(summary="s", target_language="python", same_language=True)

    result = service.propose_dependency_mappings("migrate", deps, plan)

    assert result == [mapping]
    assert agent.calls[0][2:] == ("python", True)


def test_verify_dependency_mappings_returns_unchanged_without_registry_client():
    service = MigrationService(query_runner=lambda c, p: [], planning_agent=None, generation_agent=None)
    mapping = DependencyMapping(
        current_name="flask", current_version="2.0", current_ecosystem="pypi",
        target_name="fastapi", target_version="", target_ecosystem="pypi", justification="j",
    )

    result = service.verify_dependency_mappings([mapping])

    assert result == [mapping]
    assert not result[0].verified


def test_verify_dependency_mappings_delegates_to_registry_client():
    service = MigrationService(
        query_runner=lambda c, p: [], planning_agent=None, generation_agent=None, registry_client=_StubRegistryClient(),
    )
    mapping = DependencyMapping(
        current_name="flask", current_version="2.0", current_ecosystem="pypi",
        target_name="fastapi", target_version="", target_ecosystem="pypi", justification="j",
    )

    result = service.verify_dependency_mappings([mapping])

    assert result[0].verified
    assert result[0].target_version == "9.9.9"


def test_run_includes_infra_unit_and_dependency_mapping_end_to_end(monkeypatch, tmp_path):
    (tmp_path / "Dockerfile").write_text("FROM python:3.9\n")
    (tmp_path / "requirements.txt").write_text("flask==2.0\n")

    monkeypatch.setattr("atlaz.migration.service.get_run", lambda thread_id, config=None: _FakeRun("repo-1", str(tmp_path)))
    fake_facts = SimpleNamespace(repository=SimpleNamespace(primary_languages=["python"]))
    monkeypatch.setattr("atlaz.migration.service.fetch_project_facts", lambda query_runner, thread_id, repo_id: fake_facts)
    monkeypatch.setattr("atlaz.migration.service.build_migration_units", lambda facts, repo_path=None: _units())

    def query_runner(cypher, params):
        if "build" in params.get("classifications", []) or "infra" in params.get("classifications", []):
            return [{"path": "Dockerfile"}, {"path": "requirements.txt"}]
        return []

    mapping_agent = _StubDependencyMappingAgent(
        [DependencyMapping(
            current_name="flask", current_version="2.0", current_ecosystem="pypi",
            target_name="fastapi", target_version="", target_ecosystem="pypi", justification="j", same_language=True,
        )]
    )
    service = MigrationService(
        query_runner=query_runner, planning_agent=_StubPlanningAgent(MigrationPlan(summary="s", same_language=True)),
        generation_agent=_StubGenerationAgent(), infra_generation_agent=_StubInfraAgent(),
        dependency_mapping_agent=mapping_agent, registry_client=_StubRegistryClient(),
    )

    result = service.run("thread-1", "migrate to FastAPI")

    assert any(u.unit_type == "infra" for u in result.units)
    assert len(result.dependencies) == 1
    assert result.dependency_mappings[0].verified
    assert any(g.unit_type == "infra" for g in result.generated_units)

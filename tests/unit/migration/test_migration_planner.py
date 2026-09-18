import json

from atlaz.llm.client import BaseLLMClient, MockLLMClient
from atlaz.migration.models import MigrationUnit
from atlaz.migration.planner import MigrationPlanningAgent


class ScriptedLLMClient(BaseLLMClient):
    def __init__(self, response: str):
        self.response = response
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        self.prompts_seen.append(prompt)
        return self.response


def _units() -> list[MigrationUnit]:
    return [
        MigrationUnit(unit_id="cap-1", unit_type="capability", name="Billing", description="Files: billing/service.py"),
        MigrationUnit(unit_id="cap-2", unit_type="capability", name="Auth", description="Files: auth/service.py"),
    ]


def test_run_parses_summary_and_tasks():
    response = json.dumps(
        {
            "summary": "Migrate to microservices, billing first.",
            "tasks": [
                {
                    "unit_id": "cap-1",
                    "title": "Extract billing service",
                    "description": "Stand up a FastAPI billing microservice",
                    "target_files": ["billing/main.py"],
                }
            ],
        }
    )
    agent = MigrationPlanningAgent(ScriptedLLMClient(response))

    plan = agent.run("migrate to microservices", _units())

    assert plan.summary == "Migrate to microservices, billing first."
    assert len(plan.tasks) == 1
    assert plan.tasks[0].unit_id == "cap-1"
    assert plan.tasks[0].target_files == ["billing/main.py"]


def test_run_drops_tasks_for_unknown_unit_ids():
    response = json.dumps({"summary": "s", "tasks": [{"unit_id": "cap-unknown", "title": "t", "description": "d"}]})
    agent = MigrationPlanningAgent(ScriptedLLMClient(response))

    plan = agent.run("migrate", _units())

    assert plan.tasks == []


def test_run_falls_back_to_default_summary_when_not_json():
    agent = MigrationPlanningAgent(ScriptedLLMClient("not json"))

    plan = agent.run("migrate", _units())

    assert plan.summary == "_No migration plan was generated._"


def test_run_with_mock_llm_client_degrades_gracefully():
    agent = MigrationPlanningAgent(MockLLMClient())

    plan = agent.run("migrate to microservices", _units())

    assert plan.tasks == []
    assert plan.summary


def test_run_includes_unit_descriptions_in_prompt():
    llm = ScriptedLLMClient(json.dumps({"summary": "s", "tasks": []}))
    agent = MigrationPlanningAgent(llm)

    agent.run("migrate to microservices", _units())

    prompt = llm.prompts_seen[0]
    assert "migrate to microservices" in prompt
    assert "billing/service.py" in prompt
    assert "auth/service.py" in prompt

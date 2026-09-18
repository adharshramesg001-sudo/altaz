import json

from atlaz.enhancement.models import RetrievedGuideline
from atlaz.llm.client import BaseLLMClient, MockLLMClient
from atlaz.migration.generator import UnitMigrationAgent
from atlaz.migration.models import MigrationUnit


class ScriptedLLMClient(BaseLLMClient):
    def __init__(self, response: str):
        self.response = response
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        self.prompts_seen.append(prompt)
        return self.response


def _unit() -> MigrationUnit:
    return MigrationUnit(
        unit_id="cap-1", unit_type="capability", name="Billing",
        description="Files: billing/service.py\nBusiness rule: amounts must be positive",
    )


def test_run_parses_generated_files_from_json_response():
    response = json.dumps(
        {"files": [{"file_path": "billing/main.py", "content": "def app(): ...\n"}, {"file_path": "billing/models.py", "content": "class Invoice: ...\n"}]}
    )
    agent = UnitMigrationAgent(ScriptedLLMClient(response))

    result = agent.run("migrate to FastAPI", _unit(), "Stand up a FastAPI service")

    assert len(result.files) == 2
    assert result.files[0].file_path == "billing/main.py"
    assert result.unit_id == "cap-1"


def test_run_never_includes_original_source_in_the_prompt():
    # The whole point of this flow is generation grounded only in the graph's
    # understanding -- there is no "original_content" concept here at all,
    # unlike atlaz.enhancement.modifier.CodeModificationAgent.
    llm = ScriptedLLMClient(json.dumps({"files": []}))
    agent = UnitMigrationAgent(llm)

    agent.run("migrate to FastAPI", _unit(), "Stand up a FastAPI service")

    prompt = llm.prompts_seen[0]
    assert "amounts must be positive" in prompt  # graph understanding is present
    assert "only source of truth" in prompt  # explicitly told not to assume original code


def test_run_includes_guidelines_in_prompt():
    llm = ScriptedLLMClient(json.dumps({"files": []}))
    agent = UnitMigrationAgent(llm)
    guidelines = [RetrievedGuideline(title="Naming", category="coding_standards", content="use snake_case", score=0.9)]

    agent.run("migrate to FastAPI", _unit(), "task", guidelines=guidelines)

    assert "use snake_case" in llm.prompts_seen[0]


def test_run_with_mock_llm_client_degrades_gracefully():
    agent = UnitMigrationAgent(MockLLMClient())

    result = agent.run("migrate to FastAPI", _unit(), "task")

    assert result.files == []
    assert result.unit_id == "cap-1"


def test_run_ignores_malformed_file_entries():
    response = json.dumps({"files": [{"content": "no path here"}, {"file_path": "ok.py", "content": "x = 1\n"}, "not-a-dict"]})
    agent = UnitMigrationAgent(ScriptedLLMClient(response))

    result = agent.run("migrate", _unit(), "task")

    assert len(result.files) == 1
    assert result.files[0].file_path == "ok.py"

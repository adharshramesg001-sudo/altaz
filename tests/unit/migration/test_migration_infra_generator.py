import json

from atlaz.llm.client import BaseLLMClient, MockLLMClient
from atlaz.migration.infra_generator import InfraMigrationAgent
from atlaz.migration.models import DependencyMapping


class ScriptedLLMClient(BaseLLMClient):
    def __init__(self, response: str):
        self.response = response
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        self.prompts_seen.append(prompt)
        return self.response


def test_run_shows_the_real_current_file_content_in_the_prompt():
    # The one deliberate exception to generator.py's "never show original source" rule.
    llm = ScriptedLLMClient(json.dumps({"files": []}))
    agent = InfraMigrationAgent(llm)

    agent.run(
        "migrate to FastAPI", "plan summary", {"Dockerfile": "FROM python:3.9\nCMD flask run\n"}, {},
    )

    assert "FROM python:3.9" in llm.prompts_seen[0]
    assert "CMD flask run" in llm.prompts_seen[0]


def test_run_includes_generated_unit_summaries_and_dependency_mapping():
    llm = ScriptedLLMClient(json.dumps({"files": []}))
    agent = InfraMigrationAgent(llm)
    mapping = [
        DependencyMapping(
            current_name="flask", current_version="2.0", current_ecosystem="pypi",
            target_name="fastapi", target_version="0.111.0", target_ecosystem="pypi", justification="j",
        )
    ]

    agent.run(
        "migrate to FastAPI", "plan summary", {}, {"billing": ["billing/main.py"]}, dependency_mappings=mapping,
    )

    prompt = llm.prompts_seen[0]
    assert "billing/main.py" in prompt
    assert "fastapi 0.111.0" in prompt


def test_run_parses_generated_files():
    response = json.dumps({"files": [{"file_path": "Dockerfile", "content": "FROM python:3.12\n"}]})
    agent = InfraMigrationAgent(ScriptedLLMClient(response))

    result = agent.run("migrate", "plan", {"Dockerfile": "old"}, {})

    assert result.unit_type == "infra"
    assert len(result.files) == 1
    assert result.files[0].file_path == "Dockerfile"


def test_run_with_mock_llm_client_degrades_gracefully():
    agent = InfraMigrationAgent(MockLLMClient())

    result = agent.run("migrate", "plan", {"Dockerfile": "old"}, {})

    assert result.files == []
    assert result.unit_type == "infra"

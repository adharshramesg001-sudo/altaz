import json

from atlaz.llm.client import BaseLLMClient, MockLLMClient
from atlaz.migration.dependency_mapper import DependencyMappingAgent
from atlaz.migration.models import Dependency


class ScriptedLLMClient(BaseLLMClient):
    def __init__(self, response: str):
        self.response = response
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        self.prompts_seen.append(prompt)
        return self.response


def _deps() -> list[Dependency]:
    return [
        Dependency(name="flask", version="2.0", ecosystem="pypi", manifest_path="requirements.txt"),
        Dependency(name="requests", version="2.31.0", ecosystem="pypi", manifest_path="requirements.txt"),
    ]


def test_run_parses_mappings_from_json_response():
    response = json.dumps(
        {
            "mappings": [
                {
                    "current_name": "flask",
                    "target_name": "fastapi",
                    "target_version": "0.100.0",
                    "target_ecosystem": "pypi",
                    "justification": "Direct framework replacement.",
                }
            ]
        }
    )
    agent = DependencyMappingAgent(ScriptedLLMClient(response))

    mappings = agent.run("migrate to FastAPI", _deps(), "python", True)

    by_name = {m.current_name: m for m in mappings}
    assert by_name["flask"].target_name == "fastapi"
    assert by_name["flask"].same_language is True
    # requests wasn't mentioned by the LLM -- defaults to "carried over unchanged"
    assert by_name["requests"].target_name == "requests"
    assert "carried over unchanged" in by_name["requests"].justification


def test_run_ignores_mappings_for_unknown_dependencies():
    response = json.dumps({"mappings": [{"current_name": "unknown-pkg", "target_name": "x"}]})
    agent = DependencyMappingAgent(ScriptedLLMClient(response))

    mappings = agent.run("migrate", _deps(), "python", True)

    names = {m.current_name for m in mappings}
    assert "unknown-pkg" not in names
    assert names == {"flask", "requests"}


def test_run_returns_empty_list_when_no_dependencies():
    agent = DependencyMappingAgent(ScriptedLLMClient("{}"))

    mappings = agent.run("migrate", [], "python", True)

    assert mappings == []


def test_run_with_mock_llm_client_degrades_to_unchanged_mappings():
    agent = DependencyMappingAgent(MockLLMClient())

    mappings = agent.run("migrate to Node.js", _deps(), "javascript", False)

    assert len(mappings) == 2
    assert all(not m.verified for m in mappings)
    assert all(m.same_language is False for m in mappings)


def test_run_includes_target_language_and_same_language_in_prompt():
    llm = ScriptedLLMClient(json.dumps({"mappings": []}))
    agent = DependencyMappingAgent(llm)

    agent.run("migrate to Node.js", _deps(), "javascript", False)

    prompt = llm.prompts_seen[0]
    assert "javascript" in prompt
    assert "False" in prompt
    assert "flask" in prompt

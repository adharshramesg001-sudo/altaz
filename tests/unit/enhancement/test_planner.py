import json

from atlaz.enhancement.models import ImpactAnalysisResult, ImpactedFile, RetrievedGuideline
from atlaz.enhancement.planner import PlanningAgent
from atlaz.llm.client import BaseLLMClient, MockLLMClient


class ScriptedLLMClient(BaseLLMClient):
    def __init__(self, response: str):
        self.response = response
        self.prompts_seen: list[str] = []
        self.schemas_seen: list[dict | None] = []

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        self.prompts_seen.append(prompt)
        self.schemas_seen.append(schema)
        return self.response


def _impact() -> ImpactAnalysisResult:
    return ImpactAnalysisResult(
        matched_nodes=["n1"],
        files=[
            ImpactedFile(file_path="a.py", reason="matches request"),
            ImpactedFile(file_path="b.py", reason="downstream"),
        ],
    )


def test_run_parses_summary_and_tasks_from_json_response():
    response = json.dumps(
        {
            "summary": "Replace deprecated calls with the new client.",
            "tasks": [{"file_path": "a.py", "title": "Swap client", "description": "Use the new SDK"}],
        }
    )
    llm = ScriptedLLMClient(response)
    agent = PlanningAgent(llm)

    plan = agent.run("modernize the http client", _impact())

    assert plan.summary == "Replace deprecated calls with the new client."
    assert len(plan.tasks) == 1
    assert plan.tasks[0].file_path == "a.py"
    assert plan.tasks[0].title == "Swap client"
    assert llm.schemas_seen[0] is not None


def test_run_drops_tasks_for_files_not_in_impact_result():
    response = json.dumps({"summary": "s", "tasks": [{"file_path": "unknown.py", "title": "t", "description": "d"}]})
    llm = ScriptedLLMClient(response)
    agent = PlanningAgent(llm)

    plan = agent.run("request", _impact())

    assert plan.tasks == []


def test_run_falls_back_to_default_summary_when_response_is_not_json():
    llm = ScriptedLLMClient("not json at all")
    agent = PlanningAgent(llm)

    plan = agent.run("request", _impact())

    assert plan.summary == "_No plan summary was generated._"
    assert plan.tasks == []


def test_run_with_mock_llm_client_degrades_gracefully():
    # MockLLMClient's schema-mock always returns an empty list for an "array"
    # field, so tasks come back empty -- the planning step must not error or
    # drop impacted files, since `EnhancementService.generate()` still walks
    # `impact.files` directly, not `plan.tasks`.
    agent = PlanningAgent(MockLLMClient())

    plan = agent.run("modernize the http client", _impact())

    assert plan.tasks == []
    assert plan.summary


def test_run_includes_guidelines_and_files_in_prompt():
    llm = ScriptedLLMClient(json.dumps({"summary": "s", "tasks": []}))
    agent = PlanningAgent(llm)
    guidelines = [RetrievedGuideline(title="Naming", category="coding_standards", content="use snake_case", score=0.9)]

    agent.run("modernize the http client", _impact(), guidelines)

    prompt = llm.prompts_seen[0]
    assert "modernize the http client" in prompt
    assert "a.py" in prompt and "b.py" in prompt
    assert "use snake_case" in prompt

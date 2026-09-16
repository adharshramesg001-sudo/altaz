from atlaz.enhancement.models import RetrievedGuideline
from atlaz.enhancement.modifier import CodeModificationAgent
from atlaz.llm.client import BaseLLMClient


class ScriptedLLMClient(BaseLLMClient):
    def __init__(self, response: str):
        self.response = response
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        self.prompts_seen.append(prompt)
        return self.response


def test_run_returns_raw_content_when_no_markdown_fence():
    llm = ScriptedLLMClient("def handler():\n    return 'ok'\n")
    agent = CodeModificationAgent(llm)

    result = agent.run("app.py", "def handler():\n    pass\n", "make handler return ok")

    assert result.modified_content == "def handler():\n    return 'ok'"
    assert result.file_path == "app.py"
    assert result.original_content == "def handler():\n    pass\n"


def test_run_strips_markdown_fence_with_language_tag():
    llm = ScriptedLLMClient("```python\ndef handler():\n    return 'ok'\n```")
    agent = CodeModificationAgent(llm)

    result = agent.run("app.py", "def handler():\n    pass\n", "make handler return ok")

    assert result.modified_content == "def handler():\n    return 'ok'"


def test_run_includes_guidelines_and_task_description_in_prompt():
    llm = ScriptedLLMClient("ok")
    agent = CodeModificationAgent(llm)
    guidelines = [RetrievedGuideline(title="Naming", category="coding_standards", content="use snake_case", score=0.9)]

    agent.run("app.py", "content", "add logging", guidelines=guidelines)

    prompt = llm.prompts_seen[0]
    assert "add logging" in prompt
    assert "use snake_case" in prompt
    assert "app.py" in prompt

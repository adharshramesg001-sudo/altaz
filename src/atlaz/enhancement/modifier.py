"""LLM-driven code modification for a single file, grounded in impact
analysis's matched-node reasons and the guideline store's retrieved
guidance. Calls AtlaZ's own pluggable `BaseLLMClient.complete()` (provider-
agnostic: anthropic/openai/azure/mock) rather than a hardcoded provider SDK
call, and has no regex/template fallback modifier -- `MockLLMClient` is this
project's deterministic test double, not a second "fake feature" code path,
so a real edit always requires a real provider to be configured.
"""

from __future__ import annotations

from atlaz.enhancement.models import FileModification, RetrievedGuideline
from atlaz.llm.client import BaseLLMClient

_INSTRUCTIONS = (
    "You are an expert software engineer modifying a single source file in an "
    "existing codebase to implement an enhancement. Rules:\n"
    "1. Modify ONLY what is necessary to fulfill the task description.\n"
    "2. Preserve the file's existing coding style, naming conventions, and structure.\n"
    "3. Do not remove or rewrite unrelated code.\n"
    "4. Follow the enterprise guidelines below wherever they apply.\n"
    "5. Output ONLY the complete, raw modified file contents -- no markdown fences, "
    "no commentary, no explanation. Start immediately with the code."
)


class CodeModificationAgent:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(
        self,
        file_path: str,
        current_content: str,
        task_description: str,
        guidelines: list[RetrievedGuideline] | None = None,
    ) -> FileModification:
        guideline_text = "\n".join(f"- [{g.category}] {g.title}: {g.content}" for g in guidelines or [])
        prompt = (
            f"{_INSTRUCTIONS}\n\n"
            f"FILE PATH: {file_path}\n\n"
            f"TASK DESCRIPTION:\n{task_description}\n\n"
            f"ENTERPRISE GUIDELINES:\n{guideline_text or '(none retrieved)'}\n\n"
            f"CURRENT FILE CONTENT:\n{current_content}\n\n"
            "Generate the complete modified file contents."
        )
        modified = _strip_markdown_fence(self.llm_client.complete(prompt)).strip()
        return FileModification(
            file_path=file_path,
            original_content=current_content,
            modified_content=modified,
            task_description=task_description,
        )


def _strip_markdown_fence(text: str) -> str:
    if "```" not in text:
        return text
    parts = text.split("```")
    if len(parts) < 3:
        return text
    body = parts[1]
    first_line, sep, rest = body.partition("\n")
    if sep and first_line.strip().isalpha() and len(first_line.strip()) <= 20:
        return rest
    return body

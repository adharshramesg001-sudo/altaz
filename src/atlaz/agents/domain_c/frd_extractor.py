"""FRD Extraction Agent (LLD Section 7, Corner #9).

Test files are identified by naming convention and parsed with the same
ASTParser interface as production code. For each production function, the
agent finds test functions that call it (via the call graph) and passes the
signature + calling test assertions to the LLMClient to synthesize a
plain-English behavior description.

A function with matching tests is tier EXTRACTABLE (tests are direct
evidence); a function with no test coverage falls back to INFERABLE from
signature/docstring alone, with a correspondingly lower confidence -- this
is what lets the reasoning layer tell a caller how much to trust a given
FRD entry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlaz.llm.client import BaseLLMClient
from atlaz.parsing.models import FunctionDef, ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

_TEST_FILE_PATTERN = re.compile(
    r"(^|/)(test_[^/]+|[^/]+_test|[^/]+\.test|[^/]+\.spec)\.[a-zA-Z0-9]+$"
)

_BEHAVIOR_SCHEMA = {
    "type": "object",
    "properties": {"inferred_behavior": {"type": "string"}},
    "required": ["inferred_behavior"],
}


@dataclass(slots=True)
class FunctionalRequirement:
    function_ref: str
    signature: str
    inferred_behavior: str = ""
    supporting_tests: list[str] = field(default_factory=list)
    tier: Tier = Tier.INFERABLE
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)


class FRDExtractor:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(self, parsed: list[ParsedModule]) -> list[FunctionalRequirement]:
        test_modules = [m for m in parsed if is_test_file(m.file_path)]
        production_modules = [m for m in parsed if not is_test_file(m.file_path)]

        callers_by_callee = self._build_test_callers_index(test_modules)

        requirements: list[FunctionalRequirement] = []
        for module in production_modules:
            for func in module.functions:
                supporting_tests = sorted(callers_by_callee.get(func.name, set()))
                tier = Tier.EXTRACTABLE if supporting_tests else Tier.INFERABLE
                confidence = 0.9 if supporting_tests else 0.4
                requirements.append(
                    FunctionalRequirement(
                        function_ref=func.qualified_name,
                        signature=_render_signature(func),
                        inferred_behavior=self._infer_behavior(func, supporting_tests, test_modules),
                        supporting_tests=supporting_tests,
                        tier=tier,
                        confidence=confidence,
                        evidence=[Evidence(file=module.file_path, line=func.line_start)],
                    )
                )
        return requirements

    def _build_test_callers_index(self, test_modules: list[ParsedModule]) -> dict[str, set[str]]:
        index: dict[str, set[str]] = {}
        for module in test_modules:
            for call in module.calls:
                index.setdefault(call.callee, set()).add(call.caller)
        return index

    def _infer_behavior(
        self, func: FunctionDef, supporting_tests: list[str], test_modules: list[ParsedModule]
    ) -> str:
        assertions_context = ", ".join(supporting_tests[:5]) if supporting_tests else "none"
        prompt = (
            f"Function signature: {_render_signature(func)}. "
            f"Docstring: {func.docstring or 'none'}. "
            f"Names of test functions exercising it: {assertions_context}. "
            "Write ONE plain-English sentence describing this function's intended behavior."
        )
        result = self.llm_client.complete_json(prompt, schema=_BEHAVIOR_SCHEMA)
        return result.get("inferred_behavior") or f"{func.name} behavior could not be synthesized."


def is_test_file(file_path: str) -> bool:
    return bool(_TEST_FILE_PATTERN.search(file_path))


def _render_signature(func: FunctionDef) -> str:
    params = ", ".join(f"{p.name}: {p.annotation}" if p.annotation else p.name for p in func.parameters)
    suffix = f" -> {func.return_type}" if func.return_type else ""
    return f"{func.name}({params}){suffix}"

"""LLD Parser Agent (LLD Section 8.2, Corner #13).

A thin pass-through over `ParsedModule` -- no LLM call. Per the HLD, LLD is
"the single most reliable extraction in the framework"; confidence is fixed
at 1.0 because every field traces directly to an AST node.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.parsing.models import ParamSpec, ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier


@dataclass(slots=True)
class LLDEntry:
    class_or_function: str
    signature: str
    parameters: list[ParamSpec] = field(default_factory=list)
    return_type: str | None = None
    is_method: bool = False
    parent_class: str | None = None
    file_path: str = ""
    tier: Tier = Tier.EXTRACTABLE
    confidence: float = 1.0
    evidence: list[Evidence] = field(default_factory=list)


class LLDParser:
    def run(self, parsed: list[ParsedModule]) -> list[LLDEntry]:
        entries: list[LLDEntry] = []
        for module in parsed:
            for func in module.functions:
                signature = _render_signature(func.name, func.parameters, func.return_type)
                entries.append(
                    LLDEntry(
                        class_or_function=func.qualified_name,
                        signature=signature,
                        parameters=list(func.parameters),
                        return_type=func.return_type,
                        is_method=func.is_method,
                        parent_class=func.parent_class,
                        file_path=module.file_path,
                        evidence=[Evidence(file=module.file_path, line=func.line_start)],
                    )
                )
            for cls in module.classes:
                entries.append(
                    LLDEntry(
                        class_or_function=cls.qualified_name,
                        signature=f"class {cls.name}({', '.join(cls.base_classes)})",
                        file_path=module.file_path,
                        evidence=[Evidence(file=module.file_path, line=cls.line_start)],
                    )
                )
        return entries


def _render_signature(name: str, parameters: list[ParamSpec], return_type: str | None) -> str:
    params = ", ".join(
        f"{p.name}: {p.annotation}" if p.annotation else p.name for p in parameters
    )
    suffix = f" -> {return_type}" if return_type else ""
    return f"{name}({params}){suffix}"

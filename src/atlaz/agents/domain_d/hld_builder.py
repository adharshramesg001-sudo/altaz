"""HLD Builder Agent (LLD Section 8.1, Corner #12).

Component boundaries are derived deterministically from folder topology plus
the cross-module call graph (reused from the same call-graph construction
used by the Capability Clustering agent, Section 6.1). `architecture_style`
is the one LLM-inferred field and is tiered INFERABLE independently of the
component/edge facts, which remain EXTRACTABLE. `mermaid_source` is rendered
directly from components/edges so the demo diagram and the graph can never
silently drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.agents.shared.call_graph import build_module_call_graph
from atlaz.llm.client import BaseLLMClient
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

_ARCHITECTURE_STYLE_SCHEMA = {
    "type": "object",
    "properties": {
        "architecture_style": {"type": "string"},
        "confidence": {"type": "number"},
        "rationale": {"type": "string"},
    },
    "required": ["architecture_style", "confidence"],
}


@dataclass(slots=True)
class Component:
    name: str  # top-level folder acting as a component boundary
    module_paths: list[str] = field(default_factory=list)


@dataclass(slots=True)
class DependsOnEdge:
    source_component: str
    target_component: str
    call_count: int


@dataclass(slots=True)
class ComponentDiagram:
    components: list[Component] = field(default_factory=list)
    edges: list[DependsOnEdge] = field(default_factory=list)
    architecture_style: str = "unknown"
    tier: Tier = Tier.INFERABLE  # governs architecture_style only; components/edges are EXTRACTABLE
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    mermaid_source: str = ""


class HLDBuilder:
    def __init__(self, llm_client: BaseLLMClient) -> None:
        self.llm_client = llm_client

    def run(self, parsed: list[ParsedModule]) -> ComponentDiagram:
        call_graph = build_module_call_graph(parsed)
        components = _components_from_folder_topology(parsed)
        edges = _component_edges(components, call_graph)

        style, confidence = self._infer_architecture_style(components, edges)
        diagram = ComponentDiagram(
            components=components,
            edges=edges,
            architecture_style=style,
            confidence=confidence,
            evidence=[
                Evidence(file=m.file_path, line=1) for m in parsed[:5]
            ],  # representative sample; full set lives on components
        )
        diagram.mermaid_source = _render_mermaid(diagram)
        return diagram

    def _infer_architecture_style(
        self, components: list[Component], edges: list[DependsOnEdge]
    ) -> tuple[str, float]:
        prompt = (
            "Given these software components and their dependency edges, classify the overall "
            "architecture style (e.g. layered, microservice, event-driven, monolith-modular, "
            "pipeline). Components: "
            f"{[c.name for c in components]}. Edges: "
            f"{[(e.source_component, e.target_component) for e in edges]}."
        )
        result = self.llm_client.complete_json(prompt, schema=_ARCHITECTURE_STYLE_SCHEMA)
        style = result.get("architecture_style") or "undetermined"
        try:
            confidence = float(result.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return style, max(0.0, min(1.0, confidence))


def _components_from_folder_topology(parsed: list[ParsedModule]) -> list[Component]:
    grouped: dict[str, list[str]] = {}
    for module in parsed:
        top_folder = module.file_path.split("/", 1)[0] if "/" in module.file_path else "<root>"
        grouped.setdefault(top_folder, []).append(module.file_path)
    return [Component(name=name, module_paths=paths) for name, paths in sorted(grouped.items())]


def _module_to_component(module_path: str, components: list[Component]) -> str | None:
    for component in components:
        if module_path in component.module_paths:
            return component.name
    return None


def _component_edges(components: list[Component], call_graph: dict[str, set[str]]) -> list[DependsOnEdge]:
    counts: dict[tuple[str, str], int] = {}
    for caller_module, callee_modules in call_graph.items():
        source = _module_to_component(caller_module, components)
        if source is None:
            continue
        for callee_module in callee_modules:
            target = _module_to_component(callee_module, components)
            if target is None or target == source:
                continue
            key = (source, target)
            counts[key] = counts.get(key, 0) + 1
    return [DependsOnEdge(source_component=s, target_component=t, call_count=c) for (s, t), c in counts.items()]


def _render_mermaid(diagram: ComponentDiagram) -> str:
    lines = ["graph TD"]
    for component in diagram.components:
        safe_id = _mermaid_id(component.name)
        lines.append(f'    {safe_id}["{component.name}"]')
    for edge in diagram.edges:
        lines.append(f"    {_mermaid_id(edge.source_component)} --> {_mermaid_id(edge.target_component)}")
    return "\n".join(lines)


def _mermaid_id(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name) or "root"

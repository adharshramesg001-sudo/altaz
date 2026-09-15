"""Capability Clustering Agent (LLD Section 6.1, Corner #4).

Step 1 (deterministic): build the module-level call graph (reused from
`atlaz.agents.shared.call_graph`, shared with the HLD Builder) and run
label-propagation community detection to produce raw clusters -- no LLM
involved yet.

Step 2 (LLM-assisted labeling): each raw cluster's file/function names are
passed to the LLMClient to produce a human-readable capability name plus a
confidence score. Clusters below `confidence_threshold` are left for the
consolidated HITL gate rather than written straight to the graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from atlaz.agents.shared.call_graph import build_module_call_graph
from atlaz.llm.client import BaseLLMClient
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

DEFAULT_CONFIDENCE_THRESHOLD = 0.6

_LABEL_SCHEMA = {
    "type": "object",
    "properties": {
        "capability_name": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["capability_name", "confidence"],
}


@dataclass(slots=True)
class CapabilityCluster:
    capability_name: str
    member_modules: list[str] = field(default_factory=list)
    cohesion_score: float = 0.0
    tier: Tier = Tier.INFERABLE
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)
    needs_review: bool = False


class CapabilityClusterer:
    def __init__(self, llm_client: BaseLLMClient, confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> None:
        self.llm_client = llm_client
        self.confidence_threshold = confidence_threshold

    def run(self, parsed: list[ParsedModule]) -> list[CapabilityCluster]:
        raw_clusters = self._build_raw_clusters(parsed)
        clusters: list[CapabilityCluster] = []
        for member_modules, cohesion_score in raw_clusters:
            name, confidence = self._label_cluster(member_modules, parsed)
            clusters.append(
                CapabilityCluster(
                    capability_name=name,
                    member_modules=member_modules,
                    cohesion_score=cohesion_score,
                    confidence=confidence,
                    needs_review=confidence < self.confidence_threshold,
                    evidence=[Evidence(file=m, line=1) for m in member_modules[:5]],
                )
            )
        return clusters

    def _build_raw_clusters(self, parsed: list[ParsedModule]) -> list[tuple[list[str], float]]:
        graph = nx.Graph()
        graph.add_nodes_from(m.file_path for m in parsed)
        call_graph = build_module_call_graph(parsed)
        for caller, callees in call_graph.items():
            for callee in callees:
                if graph.has_edge(caller, callee):
                    graph[caller][callee]["weight"] += 1
                else:
                    graph.add_edge(caller, callee, weight=1)

        if graph.number_of_edges() == 0:
            # No detected cross-module calls -- fall back to one cluster per
            # top-level folder so the agent still produces something
            # reviewable instead of nothing at all.
            return _fallback_folder_clusters(parsed)

        communities = nx.algorithms.community.label_propagation.label_propagation_communities(graph)
        clusters = []
        for community in communities:
            members = sorted(community)
            cohesion = _cohesion_score(graph, community)
            clusters.append((members, cohesion))
        return clusters

    def _label_cluster(self, member_modules: list[str], parsed: list[ParsedModule]) -> tuple[str, float]:
        module_by_path = {m.file_path: m for m in parsed}
        symbol_names: list[str] = []
        for path in member_modules:
            module = module_by_path.get(path)
            if module is None:
                continue
            symbol_names.extend(f.name for f in module.functions)
            symbol_names.extend(c.name for c in module.classes)

        prompt = (
            "These files and the functions/classes they define form one cohesive cluster in a codebase's "
            f"call graph. Files: {member_modules}. Symbols: {symbol_names[:40]}. "
            "Propose a short, human-readable business capability name for this cluster "
            "(e.g. 'KYC verification', 'order fulfillment')."
        )
        result = self.llm_client.complete_json(prompt, schema=_LABEL_SCHEMA)
        name = result.get("capability_name") or _fallback_name(member_modules)
        try:
            confidence = float(result.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        return name, max(0.0, min(1.0, confidence))


def _cohesion_score(graph: nx.Graph, community: set[str]) -> float:
    if len(community) <= 1:
        return 1.0
    subgraph = graph.subgraph(community)
    possible_edges = len(community) * (len(community) - 1) / 2
    return round(subgraph.number_of_edges() / possible_edges, 3) if possible_edges else 0.0


def _fallback_folder_clusters(parsed: list[ParsedModule]) -> list[tuple[list[str], float]]:
    grouped: dict[str, list[str]] = {}
    for module in parsed:
        folder = module.file_path.split("/", 1)[0] if "/" in module.file_path else "<root>"
        grouped.setdefault(folder, []).append(module.file_path)
    return [(paths, 0.0) for paths in grouped.values()]


def _fallback_name(member_modules: list[str]) -> str:
    if not member_modules:
        return "unnamed-capability"
    folder = member_modules[0].split("/", 1)[0] if "/" in member_modules[0] else member_modules[0]
    return folder

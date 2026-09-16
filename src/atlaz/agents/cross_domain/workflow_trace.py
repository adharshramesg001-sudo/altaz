"""Workflow Trace Agent (LLD Section 7.6).

Walks the method-level call graph from entry points (functions/methods
nothing else in the graph statically calls) to infer combined cross-module
purpose, seeded by Domain B's capability clusters and Domain D's HLD
service boundaries -- the two domains that produce graph-shaped output a
call-graph walk can traverse. Writes to its own top-level `state`
key (`workflow_traces`), never nested under either domain: it is a
*derived* artifact combining two domains, and nesting it under one would
misattribute provenance.

The walk is intentionally a bounded, depth-limited, single-path BFS from
each entry point (first unvisited static callee at each hop) -- a full
all-paths trace would be combinatorial and mostly noise; this gives one
representative path per entry point, which is enough to say "this entry
point's call chain touches capability X via component Y."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.analysis.call_graph import CallGraph
from atlaz.analysis.symbol_table import SymbolTable
from atlaz.shared.evidence import Evidence

DEFAULT_MAX_DEPTH = 4
DEFAULT_MAX_TRACES = 25


@dataclass(slots=True)
class WorkflowTrace:
    workflow_name: str
    entry_point: str  # qualified name
    steps: list[str] = field(default_factory=list)  # qualified names, entry point first
    capability_name: str | None = None
    component_name: str | None = None
    confidence: float = 0.0
    evidence: list[Evidence] = field(default_factory=list)


def build_workflow_traces(
    clusters: list[CapabilityCluster],
    diagram: ComponentDiagram,
    call_graph: CallGraph,
    symbol_table: SymbolTable,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_traces: int = DEFAULT_MAX_TRACES,
) -> list[WorkflowTrace]:
    callees_by_caller: dict[str, list[str]] = {}
    called_targets: set[str] = set()
    for edge in call_graph.edges:
        if edge.resolution != "static":
            continue
        callees_by_caller.setdefault(edge.caller, []).append(edge.callee)
        called_targets.add(edge.callee)

    entry_points = sorted(
        qn
        for qn, entry in symbol_table.symbols.items()
        if entry.kind in ("function", "method") and qn not in called_targets and qn in callees_by_caller
    )

    traces: list[WorkflowTrace] = []
    for entry in entry_points[:max_traces]:
        steps = _walk(entry, callees_by_caller, max_depth)
        if len(steps) < 2:
            continue  # not a meaningful multi-hop workflow
        entry_symbol = symbol_table.symbols[entry]
        capability_name = _match_capability(entry_symbol.file_path, clusters)
        component_name = _match_component(entry_symbol.file_path, diagram)
        confidence = 0.5 if capability_name and component_name else 0.3
        traces.append(
            WorkflowTrace(
                workflow_name=f"workflow::{entry_symbol.name}",
                entry_point=entry,
                steps=steps,
                capability_name=capability_name,
                component_name=component_name,
                confidence=confidence,
                evidence=[Evidence(file=entry_symbol.file_path, line=entry_symbol.line_start)],
            )
        )
    return traces


def _walk(start: str, callees_by_caller: dict[str, list[str]], max_depth: int) -> list[str]:
    steps = [start]
    visited = {start}
    current = start
    for _ in range(max_depth):
        next_step = next((c for c in callees_by_caller.get(current, []) if c not in visited), None)
        if next_step is None:
            break
        steps.append(next_step)
        visited.add(next_step)
        current = next_step
    return steps


def _match_capability(file_path: str, clusters: list[CapabilityCluster]) -> str | None:
    for cluster in clusters:
        if file_path in cluster.member_modules:
            return cluster.capability_name
    return None


def _match_component(file_path: str, diagram: ComponentDiagram) -> str | None:
    for component in diagram.components:
        if file_path in component.module_paths:
            return component.name
    return None

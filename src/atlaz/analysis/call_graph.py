"""Method-level call graph (LLD Section 5, node N6 `build_call_graph`).

Directed `Method -[CALLS]-> Method` edges, resolved via the symbol table
where statically determinable; unresolved dynamic dispatch targets are kept
with `resolution="dynamic_unresolved"` rather than dropped, exactly as the
LLD requires. This is the method-level counterpart to
`atlaz.agents.shared.call_graph.build_module_call_graph`, which stays as-is
for the module-level clustering/HLD agents that already depend on it -- the
two operate at different granularities for different consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.analysis.symbol_table import SymbolTable
from atlaz.parsing.models import ParsedModule


@dataclass(slots=True)
class CallGraphEdge:
    caller: str  # qualified name, or "<module>::<file_path>" for module-level calls
    callee: str  # resolved qualified name, or the raw callee name if unresolved
    resolution: str  # "static" | "dynamic_unresolved"
    file_path: str
    line: int


@dataclass(slots=True)
class CallGraph:
    edges: list[CallGraphEdge] = field(default_factory=list)

    def callees_of(self, caller: str) -> list[str]:
        return [e.callee for e in self.edges if e.caller == caller and e.resolution == "static"]

    def callers_of(self, callee: str) -> list[str]:
        return [e.caller for e in self.edges if e.callee == callee and e.resolution == "static"]


def build_call_graph(parsed: list[ParsedModule], symbol_table: SymbolTable) -> CallGraph:
    edges: list[CallGraphEdge] = []
    for module in parsed:
        for call in module.calls:
            caller = call.caller if call.caller != "<module>" else f"<module>::{module.file_path}"
            resolved = symbol_table.resolve_callee(call.callee, exclude_file=None)
            if resolved is not None:
                edges.append(
                    CallGraphEdge(
                        caller=caller,
                        callee=resolved.qualified_name,
                        resolution="static",
                        file_path=module.file_path,
                        line=call.line,
                    )
                )
            else:
                edges.append(
                    CallGraphEdge(
                        caller=caller,
                        callee=call.callee,
                        resolution="dynamic_unresolved",
                        file_path=module.file_path,
                        line=call.line,
                    )
                )
    return CallGraph(edges=edges)

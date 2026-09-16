"""Data flow analysis (LLD Section 5, node N7 `analyze_data_flow`).

Deliberately scoped, not exhaustive: general-purpose data-flow analysis
(full variable-level read/write tracking across an arbitrary language) is
out of reach for this build. What's real here:

- **Parameter propagation**: for each function, which of its own callees it
  forwards control to -- a best-effort call-adjacency view resolved
  directly against `symbol_table`, not full alias/taint tracking.
- **DB read/write attribution**: a method is attributed to its parent
  class (best-effort proxy for "the table this class models" -- exact for
  ORM-style entities, where `DataEntity.entity_name` is the class name)
  when its name matches a common CRUD verb; anything that doesn't match a
  known verb is attributed with `access="unknown"` rather than guessed.
  `graph_builder` only writes the resulting `Method -[:READS|:WRITES]->
  Table` edge when that class name actually matches a real `Table` node,
  same as any other edge whose target might not exist.

Per the LLD's own node spec (§5, N7: "Input: symbol_table"), this node
takes only `parsed`/`symbol_table` as input -- not `call_graph` or
`config_schema_api` -- so it can run in the same parallel superstep as N6/
N8 (all three are dispatched from N5 in the LLD's own topology diagram,
not chained from each other).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlaz.analysis.symbol_table import SymbolTable
from atlaz.parsing.models import ParsedModule

_WRITE_VERBS = re.compile(r"^(create|insert|save|add|update|delete|remove|set|write|persist|store)_?", re.IGNORECASE)
_READ_VERBS = re.compile(r"^(get|find|fetch|list|query|read|load|select|search)_?", re.IGNORECASE)


@dataclass(slots=True)
class ParameterFlow:
    function: str  # qualified name
    propagates_to: list[str] = field(default_factory=list)  # callee qualified names


@dataclass(slots=True)
class TableAccess:
    method: str  # qualified name
    table: str  # best-effort: the method's parent class name
    access: str  # "read" | "write" | "unknown"
    file_path: str
    line: int


@dataclass(slots=True)
class DataFlow:
    parameter_flows: list[ParameterFlow] = field(default_factory=list)
    table_accesses: list[TableAccess] = field(default_factory=list)


def analyze_data_flow(parsed: list[ParsedModule], symbol_table: SymbolTable) -> DataFlow:
    return DataFlow(
        parameter_flows=_build_parameter_flows(parsed, symbol_table),
        table_accesses=_build_table_accesses(symbol_table),
    )


def _build_parameter_flows(parsed: list[ParsedModule], symbol_table: SymbolTable) -> list[ParameterFlow]:
    by_caller: dict[str, set[str]] = {}
    for module in parsed:
        for call in module.calls:
            if call.caller == "<module>":
                continue
            resolved = symbol_table.resolve_callee(call.callee)
            if resolved is None:
                continue
            by_caller.setdefault(call.caller, set()).add(resolved.qualified_name)
    return [ParameterFlow(function=caller, propagates_to=sorted(callees)) for caller, callees in by_caller.items()]


def _build_table_accesses(symbol_table: SymbolTable) -> list[TableAccess]:
    accesses: list[TableAccess] = []
    for entry in symbol_table.symbols.values():
        if entry.kind != "method" or not entry.parent_class:
            continue
        accesses.append(
            TableAccess(
                method=entry.qualified_name,
                table=entry.parent_class,
                access=_classify_access(entry.name),
                file_path=entry.file_path,
                line=entry.line_start,
            )
        )
    return accesses


def _classify_access(function_name: str) -> str:
    if _WRITE_VERBS.match(function_name):
        return "write"
    if _READ_VERBS.match(function_name):
        return "read"
    return "unknown"

"""Dependency graph merge (LLD Section 5, node N9 `merge_dependency_graph`).

Fan-in from N6/N7/N8: the single deterministic substrate every downstream
domain agent reads from. This is the last node before probabilistic (LLM)
work begins -- everything before this line is deterministic and
evidence-grade by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlaz.analysis.call_graph import CallGraph
from atlaz.analysis.config_schema_api import ConfigSchemaAPI
from atlaz.analysis.data_flow import DataFlow
from atlaz.analysis.symbol_table import SymbolTable


@dataclass(slots=True)
class DependencyGraph:
    symbol_table: SymbolTable
    call_graph: CallGraph
    data_flow: DataFlow
    config_schema_api: ConfigSchemaAPI


def merge_dependency_graph(
    symbol_table: SymbolTable,
    call_graph: CallGraph,
    data_flow: DataFlow,
    config_schema_api: ConfigSchemaAPI,
) -> DependencyGraph:
    return DependencyGraph(
        symbol_table=symbol_table,
        call_graph=call_graph,
        data_flow=data_flow,
        config_schema_api=config_schema_api,
    )

"""Symbol table (LLD Section 5, node N5 `build_symbol_table`).

Fan-in from N4 (`parse_ast`): merges every successfully-parsed module's
classes/functions into one deduplicated table, keyed by qualified name, with
a simple-name index for call-graph resolution (N6). Modules that failed to
parse (`ast_index[path] is None`) contribute nothing here -- they are never
allowed to block the fan-in, per N4's documented failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.parsing.models import ParsedModule


@dataclass(slots=True)
class SymbolEntry:
    qualified_name: str
    name: str
    kind: str  # "class" | "function" | "method"
    file_path: str
    line_start: int
    line_end: int
    parent_class: str | None = None


@dataclass(slots=True)
class SymbolTable:
    symbols: dict[str, SymbolEntry] = field(default_factory=dict)  # qualified_name -> entry
    by_simple_name: dict[str, list[str]] = field(default_factory=dict)  # name -> [qualified_name, ...]

    def resolve(self, qualified_name: str) -> SymbolEntry | None:
        return self.symbols.get(qualified_name)

    def resolve_callee(self, callee_name: str, *, exclude_file: str | None = None) -> SymbolEntry | None:
        """Resolves a raw `CallEdge.callee` to exactly one symbol. A name
        defined in more than one place is left unresolved (`None`) rather
        than guessed, matching `agents.shared.call_graph`'s existing
        resolution policy at the module level."""
        candidates = [
            self.symbols[qn]
            for qn in self.by_simple_name.get(callee_name, [])
            if exclude_file is None or self.symbols[qn].file_path != exclude_file
        ]
        if len(candidates) == 1:
            return candidates[0]
        return None


def build_symbol_table(parsed: list[ParsedModule]) -> SymbolTable:
    table = SymbolTable()
    for module in parsed:
        for cls in module.classes:
            _add(table, SymbolEntry(
                qualified_name=cls.qualified_name,
                name=cls.name,
                kind="class",
                file_path=module.file_path,
                line_start=cls.line_start,
                line_end=cls.line_end,
            ))
        for func in module.functions:
            _add(table, SymbolEntry(
                qualified_name=func.qualified_name,
                name=func.name,
                kind="method" if func.is_method else "function",
                file_path=module.file_path,
                line_start=func.line_start,
                line_end=func.line_end,
                parent_class=func.parent_class,
            ))
    return table


def _add(table: SymbolTable, entry: SymbolEntry) -> None:
    table.symbols[entry.qualified_name] = entry
    table.by_simple_name.setdefault(entry.name, []).append(entry.qualified_name)

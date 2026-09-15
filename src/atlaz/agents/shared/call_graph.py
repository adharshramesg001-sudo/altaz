"""Module-level call graph construction, shared between the HLD Builder
(Section 8.1) and Capability Clustering (Section 6.1) agents. Built once
from `ParsedModule` objects and reused rather than recomputed, exactly as
the LLD specifies for both consumers.

Two signal sources are combined:
- import edges: an import statement resolved to a known module in the
  repo is a strong, unambiguous cross-module dependency signal.
- call edges: a call to a symbol defined in exactly one other parsed
  module is used too; a symbol defined in multiple modules is left
  unresolved rather than guessed, since a wrong edge here would corrupt
  both the component diagram and the capability clusters built on top of it.
"""

from __future__ import annotations

from atlaz.parsing.models import ParsedModule


def build_module_call_graph(parsed: list[ParsedModule]) -> dict[str, set[str]]:
    """Returns {caller_file_path: {callee_file_path, ...}}."""
    qualname_to_path = {m.module_qualified_name: m.file_path for m in parsed if m.module_qualified_name}
    symbol_to_paths: dict[str, set[str]] = {}
    for module in parsed:
        for fn in module.functions:
            symbol_to_paths.setdefault(fn.name, set()).add(module.file_path)
        for cls in module.classes:
            symbol_to_paths.setdefault(cls.name, set()).add(module.file_path)

    graph: dict[str, set[str]] = {module.file_path: set() for module in parsed}

    for module in parsed:
        for imp in module.imports:
            resolved = _resolve_import_to_path(imp.imported, qualname_to_path)
            if resolved and resolved != module.file_path:
                graph[module.file_path].add(resolved)

        for call in module.calls:
            candidates = symbol_to_paths.get(call.callee, set()) - {module.file_path}
            if len(candidates) == 1:
                graph[module.file_path].add(next(iter(candidates)))

    return graph


def _resolve_import_to_path(imported: str, qualname_to_path: dict[str, str]) -> str | None:
    if imported in qualname_to_path:
        return qualname_to_path[imported]
    best_match: str | None = None
    best_len = 0
    for qualname, path in qualname_to_path.items():
        if imported.startswith(qualname + ".") or qualname.startswith(imported + "."):
            match_len = min(len(imported), len(qualname))
            if match_len > best_len:
                best_len = match_len
                best_match = path
    return best_match

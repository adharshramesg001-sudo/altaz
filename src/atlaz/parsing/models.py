"""Language-neutral parse output shared by every parser backend (LLD Section 4.2).

No agent above the parsing layer ever imports `ast`, a tree-sitter grammar,
or any other language-specific parser directly -- every agent calls
`ASTParser.parse_file()` and works with `ParsedModule`, checking
`parse_depth` when it matters. That is what keeps the framework honestly
language-agnostic rather than only pretending to be.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ParseDepth(str, Enum):
    """Three-tier parsing fidelity (LLD Section 4.3)."""

    FULL_AST = "full_ast"  # native, semantically precise (stdlib ast today: Python)
    GRAMMAR_AST = "grammar_ast"  # tree-sitter grammar: full structural parse, slightly lower precision
    HEURISTIC = "heuristic"  # regex/pattern fallback for anything with no registered grammar


@dataclass(slots=True)
class ParamSpec:
    name: str
    annotation: str | None = None
    default: str | None = None


@dataclass(slots=True)
class FunctionDef:
    qualified_name: str
    name: str
    line_start: int
    line_end: int
    parameters: list[ParamSpec] = field(default_factory=list)
    return_type: str | None = None
    decorators: list[str] = field(default_factory=list)
    docstring: str | None = None
    is_method: bool = False
    parent_class: str | None = None


@dataclass(slots=True)
class FieldSpec:
    name: str
    annotation: str | None = None
    value_expr: str | None = None  # e.g. "ForeignKey('other.id')" -- used for relationship detection
    line: int = 0


@dataclass(slots=True)
class ClassDef:
    qualified_name: str
    name: str
    line_start: int
    line_end: int
    base_classes: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    docstring: str | None = None
    fields: list[FieldSpec] = field(default_factory=list)


@dataclass(slots=True)
class ImportEdge:
    source_module: str  # the module doing the importing (usually the file's own module path)
    imported: str  # dotted path / package name imported
    line: int


@dataclass(slots=True)
class CallEdge:
    caller: str  # qualified name of the calling function, or "<module>" for module-level calls
    callee: str  # best-effort resolved or raw callee name
    line: int


@dataclass(slots=True)
class DecoratorUse:
    target: str  # qualified name of the decorated function/class
    decorator: str
    line: int


@dataclass(slots=True)
class CommentRecord:
    text: str
    line: int


@dataclass(slots=True)
class ParsedModule:
    file_path: str  # relative path, matches RepoInventory.files[i].path
    language: str
    parse_depth: ParseDepth
    classes: list[ClassDef] = field(default_factory=list)
    functions: list[FunctionDef] = field(default_factory=list)
    imports: list[ImportEdge] = field(default_factory=list)
    calls: list[CallEdge] = field(default_factory=list)
    decorators: list[DecoratorUse] = field(default_factory=list)
    comments: list[CommentRecord] = field(default_factory=list)
    module_qualified_name: str = ""
    parse_error: str | None = None

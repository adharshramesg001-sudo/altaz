"""Grammar-based AST parser (LLD Section 4.2/4.3, Tier 2: GRAMMAR_AST).

Backed by `tree-sitter-language-pack`, which bundles maintained tree-sitter
grammars for ~100 languages behind one `get_parser(name)` call. This is the
concrete implementation of the LLD's Parser Registry idea that "a new
[language] can be supported by registering a grammar, not by rewriting a
parser": every language here shares this one walker, distinguished only by
a small per-language node-type table.

Deliberate deviation from the LLD text: Section 4.2 names Babel as the
JavaScript/TypeScript backend (its "Native AST" tier). This implementation
routes JS/TS through tree-sitter as well, to avoid requiring a Node.js
toolchain in a Python-only pipeline. `ParseDepth.GRAMMAR_AST` reflects that
choice honestly instead of mislabeling tree-sitter output as Tier 1 -- the
one thing the LLD's honesty-in-parsing principle (Section 4.3) explicitly
forbids is claiming a fidelity level the parser didn't earn.

Structural precision is intentionally lower than a language-native AST:
node-type name matching is heuristic across grammars (tree-sitter grammars
are not required to share a naming convention, though most do in practice),
so a language with unusual node-type names may under-extract rather than
mis-extract. Add an entry to `LANGUAGE_NODE_TYPES` to improve precision for
a specific language without touching this walker.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tree_sitter import Node
from tree_sitter_language_pack import SupportedLanguage, get_parser

from atlaz.ingestion.models import FileRecord
from atlaz.parsing.models import (
    CallEdge,
    ClassDef,
    CommentRecord,
    FunctionDef,
    ImportEdge,
    ParamSpec,
    ParseDepth,
    ParsedModule,
)
from atlaz.parsing.parsers.base import module_qualified_name, read_source


@dataclass(slots=True)
class LanguageNodeTypes:
    function_types: set[str] = field(default_factory=lambda: {"function_declaration", "function_definition"})
    method_types: set[str] = field(default_factory=lambda: {"method_definition", "method_declaration"})
    class_types: set[str] = field(default_factory=lambda: {"class_declaration", "class_definition"})
    import_types: set[str] = field(default_factory=lambda: {"import_statement", "import_declaration"})
    call_types: set[str] = field(default_factory=lambda: {"call_expression"})
    comment_types: set[str] = field(default_factory=lambda: {"comment", "line_comment", "block_comment"})


# Languages known to `tree-sitter-language-pack`. A language not listed here
# still parses -- it just uses the (reasonable) defaults above.
LANGUAGE_NODE_TYPES: dict[str, LanguageNodeTypes] = {
    "javascript": LanguageNodeTypes(
        function_types={"function_declaration", "function", "arrow_function", "generator_function_declaration"},
        method_types={"method_definition"},
        class_types={"class_declaration"},
        import_types={"import_statement"},
    ),
    "typescript": LanguageNodeTypes(
        function_types={"function_declaration", "function", "arrow_function"},
        method_types={"method_definition", "method_signature"},
        class_types={"class_declaration", "interface_declaration"},
        import_types={"import_statement"},
    ),
    "tsx": LanguageNodeTypes(
        function_types={"function_declaration", "function", "arrow_function"},
        method_types={"method_definition", "method_signature"},
        class_types={"class_declaration", "interface_declaration"},
        import_types={"import_statement"},
    ),
    "go": LanguageNodeTypes(
        function_types={"function_declaration"},
        method_types={"method_declaration"},
        class_types={"type_declaration", "type_spec"},
        import_types={"import_spec", "import_declaration"},
        comment_types={"comment"},
    ),
    "java": LanguageNodeTypes(
        function_types=set(),
        method_types={"method_declaration", "constructor_declaration"},
        class_types={"class_declaration", "interface_declaration", "enum_declaration"},
        import_types={"import_declaration"},
    ),
    "ruby": LanguageNodeTypes(
        function_types={"method"},
        method_types={"method"},
        class_types={"class", "module"},
        import_types={"call"},  # `require`/`require_relative` surface as call nodes
    ),
    "c_sharp": LanguageNodeTypes(
        function_types=set(),
        method_types={"method_declaration", "constructor_declaration"},
        class_types={"class_declaration", "interface_declaration", "struct_declaration"},
        import_types={"using_directive"},
    ),
    "rust": LanguageNodeTypes(
        function_types={"function_item"},
        method_types=set(),
        class_types={"struct_item", "enum_item", "trait_item", "impl_item"},
        import_types={"use_declaration"},
    ),
    "php": LanguageNodeTypes(
        function_types={"function_definition"},
        method_types={"method_declaration"},
        class_types={"class_declaration", "interface_declaration"},
        import_types={"namespace_use_declaration"},
    ),
    "kotlin": LanguageNodeTypes(
        function_types={"function_declaration"},
        method_types=set(),
        class_types={"class_declaration", "object_declaration"},
        import_types={"import_header"},
    ),
}

# tree-sitter-language-pack's `SupportedLanguage` enum values are the source
# of truth for what a name resolves to; we key our table by that name.
DEFAULT_NODE_TYPES = LanguageNodeTypes()


class TreeSitterASTParser:
    def __init__(self, language: str) -> None:
        self.language = language
        self._parser = get_parser(_normalize_language_name(language))
        self._node_types = LANGUAGE_NODE_TYPES.get(language, DEFAULT_NODE_TYPES)

    def parse_file(self, file_record: FileRecord, repo_root: str) -> ParsedModule:
        module_name = module_qualified_name(file_record.path)
        module = ParsedModule(
            file_path=file_record.path,
            language=self.language,
            parse_depth=ParseDepth.GRAMMAR_AST,
            module_qualified_name=module_name,
        )
        try:
            source = read_source(file_record, repo_root)
        except OSError as exc:
            module.parse_error = f"IOError: {exc}"
            return module

        source_bytes = source.encode("utf-8", errors="replace")
        tree = self._parser.parse(source_bytes)
        if tree.root_node.has_error and tree.root_node.child_count == 0:
            module.parse_error = "tree-sitter produced an empty/error tree"
            return module

        _Walker(module, source_bytes, self._node_types).walk(tree.root_node, scope=module_name)
        return module


def _normalize_language_name(language: str) -> SupportedLanguage:
    aliases = {"csharp": "c_sharp"}
    return aliases.get(language, language)  # type: ignore[return-value]


def _text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _identifier_name(node: Node, source: bytes) -> str | None:
    name_field = node.child_by_field_name("name")
    if name_field is not None:
        return _text(name_field, source)
    for child in node.children:
        if "identifier" in child.type:
            return _text(child, source)
    return None


class _Walker:
    def __init__(self, module: ParsedModule, source: bytes, node_types: LanguageNodeTypes) -> None:
        self.module = module
        self.source = source
        self.node_types = node_types

    def walk(self, node: Node, scope: str) -> None:
        for child in node.children:
            self._visit(child, scope)

    def _visit(self, node: Node, scope: str) -> None:
        nt = self.node_types

        if node.type in nt.comment_types:
            text = _text(node, self.source).lstrip("/*# ").rstrip("*/ ").strip()
            if text:
                self.module.comments.append(CommentRecord(text=text, line=node.start_point[0] + 1))
            return

        if node.type in nt.import_types:
            name = _identifier_name(node, self.source) or _text(node, self.source)[:120]
            self.module.imports.append(
                ImportEdge(source_module=self.module.module_qualified_name, imported=name, line=node.start_point[0] + 1)
            )

        is_function = node.type in nt.function_types
        is_method = node.type in nt.method_types
        is_class = node.type in nt.class_types

        if is_function or is_method:
            name = _identifier_name(node, self.source) or f"<anonymous@{node.start_point[0] + 1}>"
            qualified = f"{scope}.{name}"
            params_node = node.child_by_field_name("parameters")
            params = _extract_params(params_node, self.source) if params_node else []
            self.module.functions.append(
                FunctionDef(
                    qualified_name=qualified,
                    name=name,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    parameters=params,
                    is_method=is_method,
                    parent_class=scope if is_method and scope != self.module.module_qualified_name else None,
                )
            )
            self._collect_calls(node, qualified)
            self.walk(node, scope=qualified)
            return

        if is_class:
            name = _identifier_name(node, self.source) or f"<anonymous@{node.start_point[0] + 1}>"
            qualified = f"{scope}.{name}"
            self.module.classes.append(
                ClassDef(
                    qualified_name=qualified,
                    name=name,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                )
            )
            self.walk(node, scope=qualified)
            return

        self.walk(node, scope=scope)

    def _collect_calls(self, function_node: Node, caller_qualified: str) -> None:
        stack = list(function_node.children)
        while stack:
            node = stack.pop()
            if node.type in self.node_types.call_types:
                callee = _call_callee_name(node, self.source)
                if callee:
                    self.module.calls.append(
                        CallEdge(caller=caller_qualified, callee=callee, line=node.start_point[0] + 1)
                    )
            stack.extend(node.children)


def _call_callee_name(call_node: Node, source: bytes) -> str | None:
    function_field = call_node.child_by_field_name("function") or (
        call_node.children[0] if call_node.children else None
    )
    if function_field is None:
        return None
    if function_field.type in {"identifier", "field_identifier"}:
        return _text(function_field, source)
    if function_field.type in {"member_expression", "attribute", "field_access", "scoped_identifier"}:
        prop = function_field.child_by_field_name("property") or function_field.child_by_field_name("field")
        if prop is not None:
            return _text(prop, source)
        return _text(function_field, source).rsplit(".", 1)[-1]
    return None


def _extract_params(params_node: Node, source: bytes) -> list[ParamSpec]:
    params: list[ParamSpec] = []
    for child in params_node.children:
        if "identifier" in child.type:
            params.append(ParamSpec(name=_text(child, source)))
        elif child.type in {"required_parameter", "optional_parameter", "parameter", "formal_parameter"}:
            name = _identifier_name(child, source)
            if name:
                params.append(ParamSpec(name=name))
    return params

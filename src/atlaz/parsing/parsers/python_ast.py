"""Native Python AST parser (LLD Section 8.2: "the single most reliable
extraction technique in the framework"). Uses the stdlib `ast` module --
this is Tier 1 (FULL_AST) parsing: every field traces directly to an AST
node, no heuristics involved.
"""

from __future__ import annotations

import ast

from atlaz.ingestion.models import FileRecord
from atlaz.parsing.models import (
    CallEdge,
    ClassDef,
    CommentRecord,
    DecoratorUse,
    FieldSpec,
    FunctionDef,
    ImportEdge,
    ParamSpec,
    ParseDepth,
    ParsedModule,
)
from atlaz.parsing.parsers.base import module_qualified_name, read_source


class PythonASTParser:
    def parse_file(self, file_record: FileRecord, repo_root: str) -> ParsedModule:
        module_name = module_qualified_name(file_record.path)
        source = read_source(file_record, repo_root)
        module = ParsedModule(
            file_path=file_record.path,
            language="python",
            parse_depth=ParseDepth.FULL_AST,
            module_qualified_name=module_name,
        )

        try:
            tree = ast.parse(source, filename=file_record.path)
        except SyntaxError as exc:
            module.parse_error = f"SyntaxError: {exc.msg} at line {exc.lineno}"
            return module

        module.comments = _extract_comments(source)
        _Visitor(module, module_name).visit(tree)
        return module


def _unparse(node: ast.AST | None) -> str | None:
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001 - best-effort rendering only
        return None


def _decorator_names(decorator_list: list[ast.expr]) -> list[str]:
    names = []
    for dec in decorator_list:
        rendered = _unparse(dec)
        if rendered:
            names.append(rendered)
    return names


def _extract_comments(source: str) -> list[CommentRecord]:
    import io
    import tokenize

    comments = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                text = tok.string.lstrip("#").strip()
                if text:
                    comments.append(CommentRecord(text=text, line=tok.start[0]))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return comments


class _Visitor(ast.NodeVisitor):
    def __init__(self, module: ParsedModule, module_name: str) -> None:
        self.module = module
        self.module_name = module_name
        self._scope_stack: list[str] = []
        self._class_stack: list[str] = []

    def _qualify(self, name: str) -> str:
        prefix = ".".join(self._scope_stack)
        return f"{self.module_name}.{prefix}.{name}" if prefix else f"{self.module_name}.{name}"

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        qualified = self._qualify(node.name)
        fields = _extract_class_fields(node)
        self.module.classes.append(
            ClassDef(
                qualified_name=qualified,
                name=node.name,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                base_classes=[_unparse(base) or "" for base in node.bases],
                decorators=_decorator_names(node.decorator_list),
                docstring=ast.get_docstring(node),
                fields=fields,
            )
        )
        for dec in node.decorator_list:
            rendered = _unparse(dec)
            if rendered:
                self.module.decorators.append(DecoratorUse(target=qualified, decorator=rendered, line=node.lineno))

        self._scope_stack.append(node.name)
        self._class_stack.append(qualified)
        self.generic_visit(node)
        self._class_stack.pop()
        self._scope_stack.pop()

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        qualified = self._qualify(node.name)
        parent_class = self._class_stack[-1] if self._class_stack else None
        params = [
            ParamSpec(
                name=arg.arg,
                annotation=_unparse(arg.annotation),
            )
            for arg in node.args.args
        ]
        defaults = node.args.defaults
        if defaults:
            for param, default in zip(params[-len(defaults) :], defaults, strict=False):
                param.default = _unparse(default)

        self.module.functions.append(
            FunctionDef(
                qualified_name=qualified,
                name=node.name,
                line_start=node.lineno,
                line_end=getattr(node, "end_lineno", node.lineno),
                parameters=params,
                return_type=_unparse(node.returns),
                decorators=_decorator_names(node.decorator_list),
                docstring=ast.get_docstring(node),
                is_method=parent_class is not None,
                parent_class=parent_class,
            )
        )
        for dec in node.decorator_list:
            rendered = _unparse(dec)
            if rendered:
                self.module.decorators.append(DecoratorUse(target=qualified, decorator=rendered, line=node.lineno))

        self._scope_stack.append(node.name)
        previous_class_stack = self._class_stack
        self._class_stack = []  # functions nested in a function are not methods
        for call in ast.walk(node):
            if isinstance(call, ast.Call):
                callee = _call_target_name(call.func)
                if callee:
                    self.module.calls.append(CallEdge(caller=qualified, callee=callee, line=call.lineno))
        self.generic_visit(node)
        self._class_stack = previous_class_stack
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.module.imports.append(
                ImportEdge(source_module=self.module_name, imported=alias.name, line=node.lineno)
            )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = node.module or ""
        for alias in node.names:
            imported = f"{base}.{alias.name}" if base else alias.name
            self.module.imports.append(
                ImportEdge(source_module=self.module_name, imported=imported, line=node.lineno)
            )


def _extract_class_fields(node: ast.ClassDef) -> list[FieldSpec]:
    fields: list[FieldSpec] = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields.append(
                FieldSpec(
                    name=stmt.target.id,
                    annotation=_unparse(stmt.annotation),
                    value_expr=_unparse(stmt.value),
                    line=stmt.lineno,
                )
            )
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    fields.append(
                        FieldSpec(name=target.id, value_expr=_unparse(stmt.value), line=stmt.lineno)
                    )
    return fields


def _call_target_name(func_node: ast.expr) -> str | None:
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
    return None

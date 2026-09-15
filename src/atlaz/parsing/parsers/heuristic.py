"""Heuristic fallback parser (LLD Section 4.3, Tier 3).

Used for any language with no registered grammar. Regex-based extraction of
function-like and class-like declarations, import statements, and comments.
Every `ParsedModule` this produces is tagged `parse_depth=HEURISTIC` so every
downstream agent knows to treat its facts at lower confidence than a real
AST parse -- this is honesty applied to parsing itself, not just to the
domain agents built on top of it.
"""

from __future__ import annotations

import re

from atlaz.ingestion.models import FileRecord
from atlaz.parsing.models import ClassDef, CommentRecord, FunctionDef, ImportEdge, ParseDepth, ParsedModule
from atlaz.parsing.parsers.base import module_qualified_name, read_source

_FUNCTION_LIKE = re.compile(
    r"^\s*(?:public|private|protected|static|export|async|func|def|function|fn)?\s*"
    r"(?:function\s+)?(?:fn\s+)?(?:func\s+)?(?:def\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*\(",
    re.MULTILINE,
)
_CLASS_LIKE = re.compile(
    r"^\s*(?:public|private|protected|export|abstract)?\s*(?:class|interface|struct|trait)\s+"
    r"([A-Za-z_][A-Za-z0-9_]*)",
    re.MULTILINE,
)
_IMPORT_LIKE = re.compile(
    r"^\s*(?:import|require|use|include|#include)\s+[\"'<]?([A-Za-z0-9_./\-]+)",
    re.MULTILINE,
)
_LINE_COMMENT = re.compile(r"(?://|#)\s?(.*)$", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)

_FUNCTION_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "return",
    "class",
    "struct",
    "interface",
}


class HeuristicFallbackParser:
    def __init__(self, language: str) -> None:
        self.language = language

    def parse_file(self, file_record: FileRecord, repo_root: str) -> ParsedModule:
        module_name = module_qualified_name(file_record.path)
        module = ParsedModule(
            file_path=file_record.path,
            language=self.language,
            parse_depth=ParseDepth.HEURISTIC,
            module_qualified_name=module_name,
        )
        try:
            source = read_source(file_record, repo_root)
        except OSError as exc:
            module.parse_error = f"IOError: {exc}"
            return module

        for match in _CLASS_LIKE.finditer(source):
            name = match.group(1)
            line = source.count("\n", 0, match.start()) + 1
            module.classes.append(
                ClassDef(qualified_name=f"{module_name}.{name}", name=name, line_start=line, line_end=line)
            )

        for match in _FUNCTION_LIKE.finditer(source):
            name = match.group(1)
            if name in _FUNCTION_KEYWORDS:
                continue
            line = source.count("\n", 0, match.start()) + 1
            module.functions.append(
                FunctionDef(qualified_name=f"{module_name}.{name}", name=name, line_start=line, line_end=line)
            )

        for match in _IMPORT_LIKE.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            module.imports.append(ImportEdge(source_module=module_name, imported=match.group(1), line=line))

        for match in _BLOCK_COMMENT.finditer(source):
            text = match.group(1).strip()
            if text:
                line = source.count("\n", 0, match.start()) + 1
                module.comments.append(CommentRecord(text=text, line=line))
        for match in _LINE_COMMENT.finditer(source):
            text = match.group(1).strip()
            if text:
                line = source.count("\n", 0, match.start()) + 1
                module.comments.append(CommentRecord(text=text, line=line))

        return module

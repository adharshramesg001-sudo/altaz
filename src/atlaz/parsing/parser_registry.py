"""ParserRegistry (LLD Section 4.2).

Resolves the correct `ASTParser` for a language without any agent above this
layer needing to know how. Python gets the native stdlib-`ast` parser
(Tier 1). Anything `tree-sitter-language-pack` recognizes gets the grammar
walker (Tier 2). Everything else falls back to the regex heuristic (Tier 3)
-- the registry never raises for an unknown language, it degrades.
"""

from __future__ import annotations

import logging

from tree_sitter_language_pack import get_parser as _get_ts_parser

from atlaz.parsing.parsers.base import ASTParser
from atlaz.parsing.parsers.heuristic import HeuristicFallbackParser
from atlaz.parsing.parsers.python_ast import PythonASTParser
from atlaz.parsing.parsers.tree_sitter_ast import _normalize_language_name

logger = logging.getLogger(__name__)

# TypeScript's JSX-flavoured files need the `tsx` grammar rather than `typescript`.
_TSX_SUFFIXED_LANGUAGES = {"typescript"}


class ParserRegistry:
    def __init__(self) -> None:
        self._cache: dict[str, ASTParser] = {}

    def resolve(self, language: str, *, file_path: str | None = None) -> ASTParser:
        cache_key = self._cache_key(language, file_path)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        parser = self._build(language, file_path)
        self._cache[cache_key] = parser
        return parser

    def _cache_key(self, language: str, file_path: str | None) -> str:
        if language in _TSX_SUFFIXED_LANGUAGES and file_path and file_path.endswith(".tsx"):
            return "tsx"
        return language

    def _build(self, language: str, file_path: str | None) -> ASTParser:
        if language == "python":
            return PythonASTParser()

        ts_language = self._cache_key(language, file_path)
        try:
            from atlaz.parsing.parsers.tree_sitter_ast import TreeSitterASTParser

            _get_ts_parser(_normalize_language_name(ts_language))  # probe: raises if unsupported
            return TreeSitterASTParser(ts_language)
        except Exception as exc:  # noqa: BLE001 - any grammar-resolution failure degrades to heuristic
            logger.info("No tree-sitter grammar for %r (%s); using heuristic fallback.", language, exc)
            return HeuristicFallbackParser(language)

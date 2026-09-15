from atlaz.parsing.parser_registry import ParserRegistry
from atlaz.parsing.parsers.heuristic import HeuristicFallbackParser
from atlaz.parsing.parsers.python_ast import PythonASTParser
from atlaz.parsing.parsers.tree_sitter_ast import TreeSitterASTParser


def test_resolve_python_returns_native_parser():
    registry = ParserRegistry()
    parser = registry.resolve("python")
    assert isinstance(parser, PythonASTParser)


def test_resolve_known_grammar_returns_tree_sitter_parser():
    registry = ParserRegistry()
    parser = registry.resolve("go")
    assert isinstance(parser, TreeSitterASTParser)


def test_resolve_unknown_language_falls_back_to_heuristic():
    registry = ParserRegistry()
    parser = registry.resolve("some-made-up-language-xyz")
    assert isinstance(parser, HeuristicFallbackParser)


def test_resolve_is_cached():
    registry = ParserRegistry()
    first = registry.resolve("python")
    second = registry.resolve("python")
    assert first is second

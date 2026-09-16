from atlaz.analysis.symbol_table import build_symbol_table
from atlaz.parsing.models import ClassDef, FunctionDef, ParseDepth, ParsedModule


def _module():
    return ParsedModule(
        file_path="app.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        classes=[ClassDef(qualified_name="app.Widget", name="Widget", line_start=1, line_end=10)],
        functions=[
            FunctionDef(qualified_name="app.Widget.get_price", name="get_price", line_start=2, line_end=3, is_method=True, parent_class="app.Widget"),
            FunctionDef(qualified_name="app.main", name="main", line_start=12, line_end=14),
        ],
    )


def test_symbols_indexed_by_qualified_name():
    table = build_symbol_table([_module()])
    assert set(table.symbols) == {"app.Widget", "app.Widget.get_price", "app.main"}
    assert table.symbols["app.Widget"].kind == "class"
    assert table.symbols["app.Widget.get_price"].kind == "method"
    assert table.symbols["app.main"].kind == "function"


def test_resolve_callee_unique_simple_name():
    table = build_symbol_table([_module()])
    resolved = table.resolve_callee("main")
    assert resolved is not None
    assert resolved.qualified_name == "app.main"


def test_resolve_callee_ambiguous_name_returns_none():
    other = ParsedModule(
        file_path="other.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[FunctionDef(qualified_name="other.main", name="main", line_start=1, line_end=2)],
    )
    table = build_symbol_table([_module(), other])
    assert table.resolve_callee("main") is None  # defined in two files -- left unresolved, not guessed


def test_resolve_callee_unknown_name_returns_none():
    table = build_symbol_table([_module()])
    assert table.resolve_callee("does_not_exist") is None

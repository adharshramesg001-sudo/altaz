from atlaz.analysis.call_graph import build_call_graph
from atlaz.analysis.symbol_table import build_symbol_table
from atlaz.parsing.models import CallEdge, FunctionDef, ParseDepth, ParsedModule


def test_static_call_resolves_to_the_unique_matching_symbol():
    module = ParsedModule(
        file_path="app.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[
            FunctionDef(qualified_name="app.main", name="main", line_start=1, line_end=2),
            FunctionDef(qualified_name="app.helper", name="helper", line_start=4, line_end=5),
        ],
        calls=[CallEdge(caller="app.main", callee="helper", line=1)],
    )
    symbol_table = build_symbol_table([module])
    graph = build_call_graph([module], symbol_table)

    edge = graph.edges[0]
    assert edge.resolution == "static"
    assert edge.caller == "app.main"
    assert edge.callee == "app.helper"


def test_unresolved_call_kept_as_dynamic_unresolved_not_dropped():
    module = ParsedModule(
        file_path="app.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[FunctionDef(qualified_name="app.main", name="main", line_start=1, line_end=2)],
        calls=[CallEdge(caller="app.main", callee="unknown_symbol", line=1)],
    )
    symbol_table = build_symbol_table([module])
    graph = build_call_graph([module], symbol_table)

    assert len(graph.edges) == 1
    assert graph.edges[0].resolution == "dynamic_unresolved"
    assert graph.edges[0].callee == "unknown_symbol"


def test_module_level_call_gets_synthetic_caller():
    module = ParsedModule(
        file_path="app.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[FunctionDef(qualified_name="app.main", name="main", line_start=1, line_end=2)],
        calls=[CallEdge(caller="<module>", callee="main", line=1)],
    )
    symbol_table = build_symbol_table([module])
    graph = build_call_graph([module], symbol_table)

    assert graph.edges[0].caller == "<module>::app.py"
    assert graph.callees_of("<module>::app.py") == ["app.main"]

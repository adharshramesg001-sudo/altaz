from atlaz.analysis.data_flow import analyze_data_flow
from atlaz.analysis.symbol_table import build_symbol_table
from atlaz.parsing.models import CallEdge, FunctionDef, ParseDepth, ParsedModule


def test_parameter_flow_follows_resolved_calls():
    module = ParsedModule(
        file_path="app.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[
            FunctionDef(qualified_name="app.main", name="main", line_start=1, line_end=2),
            FunctionDef(qualified_name="app.helper", name="helper", line_start=4, line_end=5),
        ],
        calls=[CallEdge(caller="app.main", callee="helper", line=1)],
    )
    symbol_table = build_symbol_table([module])
    flow = analyze_data_flow([module], symbol_table)

    main_flow = next(f for f in flow.parameter_flows if f.function == "app.main")
    assert main_flow.propagates_to == ["app.helper"]


def test_table_access_classified_by_verb_and_attributed_to_parent_class():
    module = ParsedModule(
        file_path="repo.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[
            FunctionDef(qualified_name="repo.Order.save_order", name="save_order", line_start=2, line_end=3, is_method=True, parent_class="repo.Order"),
            FunctionDef(qualified_name="repo.Order.get_order", name="get_order", line_start=5, line_end=6, is_method=True, parent_class="repo.Order"),
            FunctionDef(qualified_name="repo.Order.close", name="close", line_start=8, line_end=9, is_method=True, parent_class="repo.Order"),
        ],
    )
    symbol_table = build_symbol_table([module])
    flow = analyze_data_flow([module], symbol_table)

    by_method = {a.method: a for a in flow.table_accesses}
    assert by_method["repo.Order.save_order"].access == "write"
    assert by_method["repo.Order.save_order"].table == "repo.Order"
    assert by_method["repo.Order.get_order"].access == "read"
    assert by_method["repo.Order.close"].access == "unknown"


def test_standalone_functions_produce_no_table_access():
    module = ParsedModule(
        file_path="app.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[FunctionDef(qualified_name="app.get_thing", name="get_thing", line_start=1, line_end=2)],
    )
    symbol_table = build_symbol_table([module])
    flow = analyze_data_flow([module], symbol_table)
    assert flow.table_accesses == []

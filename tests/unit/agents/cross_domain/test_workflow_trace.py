from atlaz.agents.cross_domain.workflow_trace import build_workflow_traces
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_d.hld_builder import Component, ComponentDiagram
from atlaz.analysis.call_graph import CallGraph, CallGraphEdge
from atlaz.analysis.symbol_table import build_symbol_table
from atlaz.parsing.models import FunctionDef, ParseDepth, ParsedModule


def _module():
    return ParsedModule(
        file_path="app.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[
            FunctionDef(qualified_name="app.main", name="main", line_start=1, line_end=2),
            FunctionDef(qualified_name="app.helper", name="helper", line_start=4, line_end=5),
        ],
    )


def test_entry_point_traced_and_matched_to_capability_and_component():
    module = _module()
    symbol_table = build_symbol_table([module])
    call_graph = CallGraph(edges=[CallGraphEdge(caller="app.main", callee="app.helper", resolution="static", file_path="app.py", line=1)])
    cluster = CapabilityCluster(capability_name="Widgets", member_modules=["app.py"])
    diagram = ComponentDiagram(components=[Component(name="core", module_paths=["app.py"])])

    traces = build_workflow_traces([cluster], diagram, call_graph, symbol_table)

    assert len(traces) == 1
    trace = traces[0]
    assert trace.entry_point == "app.main"
    assert trace.steps == ["app.main", "app.helper"]
    assert trace.capability_name == "Widgets"
    assert trace.component_name == "core"
    assert trace.confidence == 0.5  # both capability and component matched


def test_function_with_no_callees_is_not_a_multi_hop_workflow():
    module = ParsedModule(
        file_path="app.py", language="python", parse_depth=ParseDepth.FULL_AST,
        functions=[FunctionDef(qualified_name="app.lonely", name="lonely", line_start=1, line_end=2)],
    )
    symbol_table = build_symbol_table([module])
    call_graph = CallGraph(edges=[])

    traces = build_workflow_traces([], ComponentDiagram(), call_graph, symbol_table)
    assert traces == []


def test_called_function_is_not_an_entry_point():
    module = _module()
    symbol_table = build_symbol_table([module])
    call_graph = CallGraph(edges=[CallGraphEdge(caller="app.main", callee="app.helper", resolution="static", file_path="app.py", line=1)])

    traces = build_workflow_traces([], ComponentDiagram(), call_graph, symbol_table)
    entry_points = {t.entry_point for t in traces}
    assert "app.helper" not in entry_points

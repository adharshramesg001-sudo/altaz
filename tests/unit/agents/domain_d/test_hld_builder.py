from atlaz.agents.domain_d.hld_builder import HLDBuilder
from atlaz.llm.client import MockLLMClient
from atlaz.parsing.models import CallEdge, FunctionDef, ParseDepth, ParsedModule


def _module(path: str, qualname: str, functions=None, imports=None, calls=None) -> ParsedModule:
    return ParsedModule(
        file_path=path,
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        module_qualified_name=qualname,
        functions=functions or [],
        imports=imports or [],
        calls=calls or [],
    )


def test_builds_components_from_folder_topology_and_edges_from_calls():
    api_module = _module(
        "api/handlers.py",
        "api.handlers",
        functions=[FunctionDef(qualified_name="api.handlers.create_order", name="create_order", line_start=1, line_end=5)],
        calls=[CallEdge(caller="api.handlers.create_order", callee="save_order", line=3)],
    )
    service_module = _module(
        "services/orders.py",
        "services.orders",
        functions=[FunctionDef(qualified_name="services.orders.save_order", name="save_order", line_start=1, line_end=5)],
    )

    diagram = HLDBuilder(MockLLMClient()).run([api_module, service_module])

    component_names = {c.name for c in diagram.components}
    assert component_names == {"api", "services"}

    assert any(
        e.source_component == "api" and e.target_component == "services" for e in diagram.edges
    )
    assert "graph TD" in diagram.mermaid_source
    assert diagram.tier.value == "inferable"
    assert 0.0 <= diagram.confidence <= 1.0

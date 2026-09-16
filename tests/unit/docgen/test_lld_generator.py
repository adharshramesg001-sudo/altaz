import json

from atlaz.docgen.lld_generator import generate_lld
from atlaz.docgen.models import (
    BusinessRuleFact,
    ClassFact,
    MethodFact,
    ProjectFacts,
    RepositoryFact,
    ServiceFact,
    TableFact,
)


def _facts(**overrides) -> ProjectFacts:
    kwargs = {"thread_id": "t1", "repository": RepositoryFact(repo_id="r1", name="demo")}
    kwargs.update(overrides)
    return ProjectFacts(**kwargs)


def test_methods_grouped_under_their_class():
    facts = _facts(
        classes=[ClassFact(class_id="app.Widget", name="Widget", file_id="app.py")],
        methods=[MethodFact(method_id="app.Widget.get_price", name="get_price", file_id="app.py", signature="get_price(self)", reachability="reachable")],
    )
    md = generate_lld(facts)
    assert "### `Widget` — `app.py`" in md
    assert "| get_price | `get_price(self)` | reachable |" in md
    assert "### Standalone functions" not in md


def test_methods_without_a_matching_class_are_standalone():
    facts = _facts(methods=[MethodFact(method_id="app.main", name="main", file_id="app.py", reachability="unreachable")])
    md = generate_lld(facts)
    assert "### Standalone functions" in md
    assert "| main | `app.py` |" in md


def test_unreachable_methods_get_a_callout():
    facts = _facts(methods=[MethodFact(method_id="app.dead_code", name="dead_code", file_id="app.py", reachability="unreachable")])
    md = generate_lld(facts)
    assert "dead-code candidates" in md


def test_data_model_renders_fields_table():
    fields = json.dumps([{"name": "id", "type": "int", "default": None}, {"name": "rate", "type": "float", "default": "0.05"}])
    facts = _facts(tables=[TableFact(table_id="Plan", name="Plan", source_kind="orm_model", fields_json=fields, confidence=1.0)])
    md = generate_lld(facts)
    assert "### `Plan` (orm_model, confidence 1.00)" in md
    assert "| id | int | — |" in md
    assert "| rate | float | 0.05 |" in md


def test_business_rules_table():
    facts = _facts(business_rules=[BusinessRuleFact(rule_id="cfg::rate", description="late fee", literal_value="0.05", status="confirmed", confidence=0.95)])
    md = generate_lld(facts)
    assert "`cfg::rate`" in md
    assert "late fee" in md


def test_no_conflicts_omits_the_section_entirely():
    md = generate_lld(_facts())
    assert "Cross-Domain Conflicts" not in md


def test_module_breakdown_lists_files_and_classes_per_service():
    facts = _facts(
        services=[ServiceFact(service_id="api", name="api", module_count=1)],
        service_files={"api": ["api/app.py"]},
        classes=[ClassFact(class_id="api.app.Widget", name="Widget", file_id="api/app.py")],
    )
    md = generate_lld(facts)
    assert "- `api/app.py` — Widget" in md

from atlaz.docgen.hld_generator import generate_hld
from atlaz.docgen.models import CapabilityFact, GapFact, ProjectFacts, RepositoryFact, ServiceFact
from atlaz.llm.client import MockLLMClient


def _facts(**overrides) -> ProjectFacts:
    kwargs = {"thread_id": "t1", "repository": RepositoryFact(repo_id="r1", name="demo", primary_languages=["python"])}
    kwargs.update(overrides)
    return ProjectFacts(**kwargs)


def test_header_includes_repo_and_thread_id():
    md = generate_hld(_facts(), MockLLMClient())
    assert "# High-Level Design — demo" in md
    assert "`t1`" in md
    assert "python" in md


def test_executive_summary_falls_back_when_llm_gives_nothing():
    class EmptyLLM(MockLLMClient):
        def complete_json(self, prompt, schema=None):
            return {}

    md = generate_hld(_facts(), EmptyLLM())
    assert "This document describes the architecture of demo" in md


def test_open_business_case_gap_is_noted():
    facts = _facts(gaps=[GapFact(gap_id="business_case_vision", signal_found=False, still_open=True)])
    md = generate_hld(facts, MockLLMClient())
    assert "external-only gap" in md


def test_services_render_as_a_table_and_mermaid_diagram_when_deps_exist():
    from atlaz.docgen.models import ServiceDependency

    facts = _facts(
        services=[ServiceFact(service_id="api", name="api", architecture_style="layered", module_count=3)],
        service_dependencies=[ServiceDependency(source="api", target="db", call_count=2)],
    )
    md = generate_hld(facts, MockLLMClient())
    assert "| `api` | 3 | layered |" in md
    assert "```mermaid" in md
    assert "api" in md and "db" in md


def test_no_services_produces_an_honest_absence_note():
    md = generate_hld(_facts(), MockLLMClient())
    assert "No service/component boundaries were derived" in md


def test_capabilities_table_flags_needs_review():
    facts = _facts(capabilities=[CapabilityFact(capability_id="c1", name="Billing", confidence=0.3, needs_review=True)])
    md = generate_hld(facts, MockLLMClient())
    assert "| Billing | 0.30 |" in md
    assert "| yes |" in md

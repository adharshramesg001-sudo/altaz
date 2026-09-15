from atlaz.agents.domain_c.frd_extractor import FRDExtractor, is_test_file
from atlaz.llm.client import MockLLMClient
from atlaz.parsing.models import CallEdge, FunctionDef, ParseDepth, ParsedModule


def test_is_test_file_naming_conventions():
    assert is_test_file("tests/test_billing.py")
    assert is_test_file("src/billing.test.ts")
    assert is_test_file("src/billing.spec.ts")
    assert not is_test_file("src/billing.py")


def test_function_with_test_coverage_is_extractable():
    production = ParsedModule(
        file_path="app/billing.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        functions=[FunctionDef(qualified_name="app.billing.compute_fee", name="compute_fee", line_start=1, line_end=3)],
    )
    test_module = ParsedModule(
        file_path="tests/test_billing.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        calls=[CallEdge(caller="tests.test_billing.test_compute_fee_is_positive", callee="compute_fee", line=5)],
    )

    requirements = FRDExtractor(MockLLMClient()).run([production, test_module])

    fee_req = next(r for r in requirements if r.function_ref == "app.billing.compute_fee")
    assert fee_req.tier.value == "extractable"
    assert fee_req.confidence == 0.9
    assert "tests.test_billing.test_compute_fee_is_positive" in fee_req.supporting_tests
    assert fee_req.inferred_behavior


def test_function_without_test_coverage_is_inferable_with_lower_confidence():
    production = ParsedModule(
        file_path="app/billing.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        functions=[FunctionDef(qualified_name="app.billing.untested", name="untested", line_start=1, line_end=3)],
    )

    requirements = FRDExtractor(MockLLMClient()).run([production])

    req = requirements[0]
    assert req.tier.value == "inferable"
    assert req.confidence < 0.9
    assert req.supporting_tests == []

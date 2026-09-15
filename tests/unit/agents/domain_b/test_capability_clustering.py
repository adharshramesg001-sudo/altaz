from atlaz.agents.domain_b.capability_clustering import CapabilityClusterer
from atlaz.llm.client import MockLLMClient
from atlaz.parsing.models import CallEdge, FunctionDef, ParseDepth, ParsedModule


def _module(path: str, qualname: str, functions=None, calls=None) -> ParsedModule:
    return ParsedModule(
        file_path=path,
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        module_qualified_name=qualname,
        functions=functions or [],
        calls=calls or [],
    )


def test_clusters_modules_connected_by_calls():
    kyc_a = _module(
        "kyc/verify.py",
        "kyc.verify",
        functions=[FunctionDef(qualified_name="kyc.verify.check_id", name="check_id", line_start=1, line_end=2)],
        calls=[CallEdge(caller="kyc.verify.check_id", callee="lookup_registry", line=1)],
    )
    kyc_b = _module(
        "kyc/registry.py",
        "kyc.registry",
        functions=[FunctionDef(qualified_name="kyc.registry.lookup_registry", name="lookup_registry", line_start=1, line_end=2)],
    )
    billing = _module(
        "billing/invoices.py",
        "billing.invoices",
        functions=[FunctionDef(qualified_name="billing.invoices.generate", name="generate", line_start=1, line_end=2)],
    )

    clusters = CapabilityClusterer(MockLLMClient()).run([kyc_a, kyc_b, billing])

    all_members = {m for c in clusters for m in c.member_modules}
    assert all_members == {"kyc/verify.py", "kyc/registry.py", "billing/invoices.py"}

    kyc_cluster = next(c for c in clusters if "kyc/verify.py" in c.member_modules)
    assert "kyc/registry.py" in kyc_cluster.member_modules
    assert kyc_cluster.tier.value == "inferable"
    assert kyc_cluster.capability_name  # LLM-labeled, non-empty


def test_low_confidence_cluster_is_flagged_for_review():
    module = _module("misc/thing.py", "misc.thing")
    clusterer = CapabilityClusterer(MockLLMClient(), confidence_threshold=0.9)

    clusters = clusterer.run([module])

    assert all(c.needs_review for c in clusters)  # mock confidence (0.5) < 0.9 threshold

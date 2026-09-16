import json

from atlaz.enhancement.impact_analysis import ImpactAnalysisAgent


def _file_record(file_path: str, description: str) -> dict:
    return {
        "labels": ["File"], "name": None, "rule_id": None, "function_ref": None,
        "route": None, "term": None, "control_type": None,
        "file_path": file_path, "description": description, "inferred_behavior": None,
        "definition": None, "detail": None, "member_modules": None, "evidence_json": None,
    }


def _capability_record(name: str, member_modules: list[str], description: str) -> dict:
    return {
        "labels": ["BusinessCapability"], "name": name, "rule_id": None, "function_ref": None,
        "route": None, "term": None, "control_type": None,
        "file_path": None, "description": description, "inferred_behavior": None,
        "definition": None, "detail": None, "member_modules": member_modules, "evidence_json": None,
    }


def _rule_record(rule_id: str, description: str, evidence_file: str) -> dict:
    return {
        "labels": ["BusinessRule"], "name": None, "rule_id": rule_id, "function_ref": None,
        "route": None, "term": None, "control_type": None,
        "file_path": None, "description": description, "inferred_behavior": None,
        "definition": None, "detail": None, "member_modules": None,
        "evidence_json": json.dumps([{"file": evidence_file, "line": 12, "commit": "abc", "note": ""}]),
    }


def test_scores_nodes_by_keyword_overlap_and_collects_files_from_evidence():
    records = [
        _rule_record("cfg::rate_limit", "Rate limit checkout requests per user", "checkout/service.py"),
        _file_record("billing/invoice.py", "Generates monthly invoices"),
    ]

    def fake_runner(cypher, params):
        assert "BusinessCapability" in cypher
        return records

    agent = ImpactAnalysisAgent(fake_runner)
    result = agent.run("Add a rate limit to the checkout flow")

    assert "cfg::rate_limit" in result.matched_nodes
    assert "billing/invoice.py" not in {f.file_path for f in result.files}
    assert any(f.file_path == "checkout/service.py" for f in result.files)


def test_capability_member_modules_widen_via_downstream_service_dependency():
    records = [_capability_record("Checkout", ["checkout/service.py"], "Handles checkout rate limiting")]
    widen_records = [{"capability_name": "Billing", "member_modules": ["billing/invoice.py"]}]

    calls = []

    def fake_runner(cypher, params):
        calls.append((cypher, params))
        if "DEPENDS_ON" in cypher:
            assert params["capability_names"] == ["Checkout"]
            return widen_records
        return records

    agent = ImpactAnalysisAgent(fake_runner)
    result = agent.run("rate limiting for checkout")

    file_paths = {f.file_path for f in result.files}
    assert "checkout/service.py" in file_paths
    assert "billing/invoice.py" in file_paths
    widened = next(f for f in result.files if f.file_path == "billing/invoice.py")
    assert "downstream" in widened.reason
    assert len(calls) == 2


def test_no_keyword_overlap_yields_no_impacted_files():
    def fake_runner(cypher, params):
        return [_file_record("unrelated/thing.py", "Totally unrelated module")]

    agent = ImpactAnalysisAgent(fake_runner)
    result = agent.run("completely different topic xyz")

    assert result.files == []
    assert result.matched_nodes == []

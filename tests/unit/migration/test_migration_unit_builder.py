from atlaz.docgen.models import (
    ApiFact,
    BusinessRuleFact,
    CapabilityFact,
    ClassFact,
    MethodFact,
    ProjectFacts,
    RepositoryFact,
    ServiceDependency,
    ServiceFact,
    TableFact,
    WorkflowFact,
)
from atlaz.migration.unit_builder import build_infra_unit, build_migration_units


def _facts(**overrides) -> ProjectFacts:
    defaults = {"thread_id": "t1", "repository": RepositoryFact(repo_id="r1", name="demo", primary_languages=["python"])}
    defaults.update(overrides)
    return ProjectFacts(**defaults)


def test_builds_one_unit_per_capability_when_capabilities_exist():
    facts = _facts(
        capabilities=[
            CapabilityFact(capability_id="cap-1", name="Billing", confidence=0.9, member_modules=["billing/service.py"]),
            CapabilityFact(capability_id="cap-2", name="Auth", confidence=0.8, member_modules=["auth/service.py"]),
        ],
        services=[ServiceFact(service_id="svc-1", name="api")],  # present but ignored -- capabilities take priority
    )

    units = build_migration_units(facts)

    assert [u.unit_id for u in units] == ["cap-1", "cap-2"]
    assert all(u.unit_type == "capability" for u in units)


def test_falls_back_to_services_when_no_capabilities():
    facts = _facts(services=[ServiceFact(service_id="svc-1", name="api", architecture_style="rest")])

    units = build_migration_units(facts)

    assert len(units) == 1
    assert units[0].unit_type == "service"
    assert units[0].unit_id == "svc-1"


def test_falls_back_to_whole_project_when_no_capabilities_or_services():
    facts = _facts()

    units = build_migration_units(facts)

    assert len(units) == 1
    assert units[0].unit_type == "project"


def test_capability_unit_includes_classes_and_methods_joined_by_file_id():
    facts = _facts(
        capabilities=[CapabilityFact(capability_id="cap-1", name="Billing", member_modules=["billing/service.py"])],
        classes=[
            ClassFact(class_id="c1", name="BillingService", file_id="billing/service.py"),
            ClassFact(class_id="c2", name="OtherClass", file_id="other/unrelated.py"),
        ],
        methods=[
            MethodFact(method_id="m1", name="charge", file_id="billing/service.py", signature="(amount)"),
            MethodFact(method_id="m2", name="unrelated_fn", file_id="other/unrelated.py"),
        ],
    )

    units = build_migration_units(facts)

    description = units[0].description
    assert "BillingService" in description
    assert "charge(amount)" in description
    assert "OtherClass" not in description
    assert "unrelated_fn" not in description


def test_capability_unit_includes_workflow_steps_for_its_features():
    facts = _facts(
        capabilities=[CapabilityFact(capability_id="cap-1", name="Billing", feature_ids=["feat-1"])],
        workflows=[WorkflowFact(workflow_id="wf-1", name="Charge card", feature_id="feat-1", steps=["validate", "charge", "notify"])],
    )

    units = build_migration_units(facts)

    assert "Charge card" in units[0].description
    assert "validate -> charge -> notify" in units[0].description


def test_capability_unit_pulls_related_facts_via_keyword_overlap():
    facts = _facts(
        capabilities=[CapabilityFact(capability_id="cap-1", name="Billing")],
        business_rules=[
            BusinessRuleFact(rule_id="r1", description="Billing amounts must be positive"),
            BusinessRuleFact(rule_id="r2", description="Usernames must be unique"),
        ],
        # Underscore is a word character for `tokenize()` (same as `impact_analysis.py`, which
        # this scoring was factored out of unchanged), so a snake_case name like
        # "billing_invoices" is one token and won't overlap with "billing" alone.
        tables=[TableFact(table_id="t1", name="billing"), TableFact(table_id="t2", name="user_sessions")],
        apis=[ApiFact(api_id="a1", route="/billing/charge", method="POST")],
    )

    description = build_migration_units(facts)[0].description

    assert "Billing amounts must be positive" in description
    assert "Usernames must be unique" not in description
    assert "Table billing" in description
    assert "user_sessions" not in description
    assert "/billing/charge" in description


def test_service_unit_includes_dependencies_and_files():
    facts = _facts(
        services=[ServiceFact(service_id="svc-1", name="checkout")],
        service_files={"checkout": ["checkout/api.py"]},
        service_dependencies=[ServiceDependency(source="checkout", target="payments", call_count=3)],
    )

    description = build_migration_units(facts)[0].description

    assert "checkout/api.py" in description
    assert "payments" in description


def test_build_infra_unit_returns_none_when_no_infra_files():
    assert build_infra_unit([]) is None


def test_build_infra_unit_lists_file_paths():
    unit = build_infra_unit(["Dockerfile", "requirements.txt"])

    assert unit is not None
    assert unit.unit_type == "infra"
    assert unit.file_paths == ["Dockerfile", "requirements.txt"]
    assert "Dockerfile" in unit.description
    assert "requirements.txt" in unit.description


def test_build_migration_units_without_repo_path_skips_static_value_scan():
    facts = _facts(capabilities=[CapabilityFact(capability_id="cap-1", name="Billing", member_modules=["a.py"])])

    description = build_migration_units(facts)[0].description

    assert "Static/technical values" not in description


def test_build_migration_units_with_repo_path_includes_static_values(tmp_path):
    (tmp_path / "a.py").write_text("MAX_RETRIES = 3\n")
    facts = _facts(capabilities=[CapabilityFact(capability_id="cap-1", name="Billing", member_modules=["a.py"])])

    description = build_migration_units(facts, repo_path=str(tmp_path))[0].description

    assert "MAX_RETRIES = 3" in description


def test_build_migration_units_with_repo_path_includes_response_fields(tmp_path):
    (tmp_path / "app.py").write_text('def health():\n    return {"status": "ok", "service": "inference"}\n')
    facts = _facts(capabilities=[CapabilityFact(capability_id="cap-1", name="Billing", member_modules=["app.py"])])

    unit = build_migration_units(facts, repo_path=str(tmp_path))[0]

    assert unit.known_response_fields == ["service", "status"]
    assert "service" in unit.description
    assert "MUST use exactly these field names" in unit.description


def test_build_migration_units_without_repo_path_leaves_response_fields_empty():
    facts = _facts(capabilities=[CapabilityFact(capability_id="cap-1", name="Billing", member_modules=["app.py"])])

    unit = build_migration_units(facts)[0]

    assert unit.known_response_fields == []

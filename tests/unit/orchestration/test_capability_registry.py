import pytest

from atlaz.orchestration.capability_registry import (
    CapabilityRegistryError,
    enabled_agents,
    enabled_domains,
    load_capability_registry,
    node_name,
    to_snapshot,
    validate_capability_registry,
)


def test_repo_root_registry_loads_and_matches_domain_e_all_false():
    registry = load_capability_registry()
    assert registry["domain_e"] == {
        "infra_iac_parser": False,
        "test_coverage_analyzer": False,
        "git_pr_history_miner": False,
    }
    assert registry["domain_a"]["gap_detector"] is True


def test_enabled_agents_and_domains():
    registry = {"domain_b": {"a": True, "b": False}, "domain_e": {"c": False}}
    assert enabled_agents(registry, "domain_b") == ["a"]
    assert enabled_agents(registry, "domain_e") == []
    assert enabled_domains(registry) == ["domain_b"]


def test_validate_passes_when_every_enabled_agent_is_implemented():
    registry = {"domain_b": {"capability_clustering": True}}
    validate_capability_registry(registry, {node_name("domain_b", "capability_clustering")})


def test_validate_raises_hard_failure_for_enabled_but_unimplemented_agent():
    registry = {"domain_b": {"brd_extraction": True}}
    with pytest.raises(CapabilityRegistryError, match="domain_b.brd_extraction"):
        validate_capability_registry(registry, set())


def test_validate_ignores_disabled_agents_with_no_implementation():
    registry = {"domain_e": {"infra_iac_parser": False}}
    validate_capability_registry(registry, set())  # must not raise


def test_load_missing_file_raises():
    with pytest.raises(CapabilityRegistryError):
        load_capability_registry("/nonexistent/capability_registry.yaml")


def test_to_snapshot_is_json_safe_copy():
    registry = {"domain_a": {"gap_detector": True}}
    snapshot = to_snapshot(registry)
    registry["domain_a"]["gap_detector"] = False
    assert snapshot["domains"]["domain_a"]["gap_detector"] is True  # snapshot is a copy, not a live view

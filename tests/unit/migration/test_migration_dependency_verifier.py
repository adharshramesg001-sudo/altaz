from atlaz.migration.dependency_verifier import verify_dependency_mappings
from atlaz.migration.models import DependencyMapping


class FakeRegistryClient:
    def __init__(self, responses: dict[str, dict | None]):
        self.responses = responses
        self.urls_seen: list[str] = []

    def get_json(self, url: str) -> dict | None:
        self.urls_seen.append(url)
        for key, value in self.responses.items():
            if key in url:
                return value
        return None


def _mapping(target_name="fastapi", target_ecosystem="pypi") -> DependencyMapping:
    return DependencyMapping(
        current_name="flask", current_version="2.0", current_ecosystem="pypi",
        target_name=target_name, target_version="0.0.0", target_ecosystem=target_ecosystem,
        justification="j",
    )


def test_verifies_existing_pypi_package():
    client = FakeRegistryClient({"pypi.org/pypi/fastapi": {"info": {"version": "0.111.0"}}})

    result = verify_dependency_mappings([_mapping()], client)

    assert result[0].verified
    assert result[0].target_version == "0.111.0"
    assert "PyPI" in result[0].verification_note


def test_flags_nonexistent_pypi_package():
    client = FakeRegistryClient({})

    result = verify_dependency_mappings([_mapping(target_name="totally-not-a-real-package-xyz")], client)

    assert not result[0].verified
    assert "not found" in result[0].verification_note


def test_verifies_existing_npm_package():
    client = FakeRegistryClient({"registry.npmjs.org/axios": {"dist-tags": {"latest": "1.6.0"}}})

    result = verify_dependency_mappings([_mapping(target_name="axios", target_ecosystem="npm")], client)

    assert result[0].verified
    assert result[0].target_version == "1.6.0"


def test_unsupported_ecosystem_is_flagged_not_silently_confirmed():
    client = FakeRegistryClient({})

    result = verify_dependency_mappings([_mapping(target_name="some-gem", target_ecosystem="rubygems")], client)

    assert not result[0].verified
    assert "not supported" in result[0].verification_note


def test_verify_dependency_mappings_handles_empty_list():
    assert verify_dependency_mappings([], FakeRegistryClient({})) == []

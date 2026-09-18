"""Deterministically verifies a proposed dependency mapping against the
real target-ecosystem package registry -- the one part of dependency
mapping that *can* be proven, unlike feature-equivalence (see
`dependency_mapper.py`'s docstring). Existence + real current version only;
never confirms the proposal is functionally correct for this codebase.

v1 supports PyPI and npm (the two ecosystems this project's own demo repos
exercise); any other `target_ecosystem` is left `verified=False` with a
note that verification isn't supported yet, never silently treated as
confirmed. `RegistryClient` is injected (same DI shape as `LLMClient`/
`VectorIndex` elsewhere in this codebase) so tests never make a real
network call.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from atlaz.migration.models import DependencyMapping

_PYPI_URL = "https://pypi.org/pypi/{name}/json"
_NPM_URL = "https://registry.npmjs.org/{name}"


@runtime_checkable
class RegistryClient(Protocol):
    def get_json(self, url: str) -> dict | None:
        """Return the parsed JSON body, or None on any non-2xx/network failure."""
        ...


class HttpRegistryClient:
    def __init__(self, timeout_seconds: float = 10.0) -> None:
        self.timeout_seconds = timeout_seconds

    def get_json(self, url: str) -> dict | None:
        import httpx

        try:
            response = httpx.get(url, timeout=self.timeout_seconds)
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None


def verify_dependency_mappings(mappings: list[DependencyMapping], client: RegistryClient) -> list[DependencyMapping]:
    return [_verify_one(mapping, client) for mapping in mappings]


def _verify_one(mapping: DependencyMapping, client: RegistryClient) -> DependencyMapping:
    ecosystem = mapping.target_ecosystem.lower().strip()
    if ecosystem == "pypi":
        data = client.get_json(_PYPI_URL.format(name=mapping.target_name))
        if data is None:
            mapping.verified = False
            mapping.verification_note = f"'{mapping.target_name}' was not found on PyPI."
            return mapping
        latest = data.get("info", {}).get("version") or mapping.target_version
        mapping.verified = True
        mapping.target_version = latest
        mapping.verification_note = f"Verified on PyPI, latest version {latest}."
        return mapping

    if ecosystem == "npm":
        data = client.get_json(_NPM_URL.format(name=mapping.target_name))
        if data is None:
            mapping.verified = False
            mapping.verification_note = f"'{mapping.target_name}' was not found on npm."
            return mapping
        latest = data.get("dist-tags", {}).get("latest") or mapping.target_version
        mapping.verified = True
        mapping.target_version = latest
        mapping.verification_note = f"Verified on npm, latest version {latest}."
        return mapping

    mapping.verified = False
    mapping.verification_note = f"Verification not supported yet for ecosystem '{mapping.target_ecosystem}'."
    return mapping

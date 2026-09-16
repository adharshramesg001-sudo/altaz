"""Capability registry (LLD Section 6.1, node `check_capability_registry`).

Direct fix for the review gap "is 'not built' enforced at runtime, or only a
diagram note?": `load_capability_registry` reads `capability_registry.yaml`
(versioned alongside the code, never hand-edited per run), and
`validate_capability_registry` checks it against the LangGraph node names
`atlaz.orchestration.graph.build_state_graph` actually registers -- an agent
marked `true` in the YAML with no corresponding node registered is a
`RuntimeError` at graph-compile time, not a silently-skipped `Send()`.

Every agent is identified by the string `f"{domain}.{agent}"` (e.g.
`"domain_b.capability_clustering"`). `domain_orchestrator` (LLD N10ORCH)
fans out via `Send()` at *domain* granularity (one LangGraph node per
domain, since this build's within-domain agents have no cross-agent
parallelism concerns worth a full per-agent `Send()`); each domain's node
function is the thing that actually enforces per-agent gating, by checking
`registry[domain][agent]` before invoking that agent's code. `validate_
capability_registry` therefore checks the registry against a maintained
set of *implemented* agent identifiers (`atlaz.orchestration.nodes.
IMPLEMENTED_AGENTS`), not literal LangGraph node names -- the LLD's actual
requirement ("not built" must be a runtime-checked fact, not just a
diagram note) is satisfied either way; this codebase's agent-vs-node
granularity just doesn't map one-to-one.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

import yaml

DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "capability_registry.yaml"


class CapabilityRegistryError(RuntimeError):
    """Raised when the registry references an agent with no registered node,
    or the YAML itself is malformed."""


CapabilityRegistry = dict[str, dict[str, bool]]


def load_capability_registry(path: str | Path | None = None) -> CapabilityRegistry:
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    try:
        raw = registry_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CapabilityRegistryError(f"capability registry not found: {registry_path}") from exc

    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        raise CapabilityRegistryError(f"capability registry is not a mapping: {registry_path}")

    registry: CapabilityRegistry = {}
    for domain, agents in data.items():
        if not isinstance(agents, dict):
            raise CapabilityRegistryError(f"domain {domain!r} entry must be a mapping of agent -> bool")
        registry[domain] = {agent: bool(enabled) for agent, enabled in agents.items()}
    return registry


def node_name(domain: str, agent: str) -> str:
    return f"{domain}.{agent}"


def validate_capability_registry(registry: CapabilityRegistry, implemented_agents: set[str]) -> None:
    missing: list[str] = []
    for domain, agents in registry.items():
        for agent, enabled in agents.items():
            if not enabled:
                continue
            name = node_name(domain, agent)
            if name not in implemented_agents:
                missing.append(name)
    if missing:
        raise CapabilityRegistryError(
            "capability_registry.yaml marks the following agent(s) enabled, but no matching "
            f"implementation is registered: {', '.join(sorted(missing))}"
        )


def enabled_agents(registry: CapabilityRegistry, domain: str) -> list[str]:
    return sorted(agent for agent, enabled in registry.get(domain, {}).items() if enabled)


def enabled_domains(registry: CapabilityRegistry) -> list[str]:
    """A domain is "enabled" for fan-out if at least one of its agents is."""
    return sorted(domain for domain, agents in registry.items() if any(agents.values()))


class CapabilitySnapshot(TypedDict):
    """JSON-safe shape stored on `pipeline_runs.capability_registry_snapshot`
    (LLD Section 14.4) -- the registry as it stood for this specific run."""

    domains: dict[str, dict[str, bool]]


def to_snapshot(registry: CapabilityRegistry) -> CapabilitySnapshot:
    return {"domains": {domain: dict(agents) for domain, agents in registry.items()}}

"""Stable, serialization-surviving keys for matching a HITL resolution back
to the domain-list object it resolves.

Object identity (`id()`) does NOT survive a LangGraph checkpoint round-trip:
every node re-executes against state freshly deserialized from SQLite, and
the deserializer reconstructs each dataclass as a new object rather than
preserving cross-field aliasing -- confirmed directly (two references to
what was the same in-memory `CapabilityCluster` before a checkpoint write
come back as two distinct objects, equal by value, different by `id()`,
after it). A resume that happens in a different process (an HTTP API and a
reviewing client are the normal case, not an edge case) makes this the only
possible outcome, not just a same-process quirk. Every low-confidence
finding is therefore keyed by a small business-meaningful string instead,
computed identically wherever an item is flagged (`hitl.merge`) and wherever
a resolution is applied back (`hitl.resolution_application`).
"""

from __future__ import annotations

from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.hld_builder import ComponentDiagram
from atlaz.agents.domain_d.security_control_scanner import SecurityControl


def natural_key(subject: object) -> str:
    """Note: `CapabilityCluster.capability_name` is also the Neo4j MERGE key
    for the Capability node (`graph_store.schema.NATURAL_KEY_FIELD`), so two
    clusters an LLM happens to name identically already collapse into one
    graph node regardless of HITL matching -- this key intentionally stays
    consistent with that rather than inventing a different identity for the
    same object. `MockLLMClient` makes this collision far more visible than
    a real provider would (it always returns the same placeholder name),
    which is expected mock behavior, not a bug in the matching itself."""
    if isinstance(subject, CapabilityCluster):
        return subject.capability_name
    if isinstance(subject, GlossaryTerm):
        return subject.term
    if isinstance(subject, FunctionalRequirement):
        return subject.function_ref
    if isinstance(subject, ComponentDiagram):
        return f"architecture_style={subject.architecture_style}"
    if isinstance(subject, SecurityControl):
        return f"regulation_hypothesis for {subject.location}"
    raise TypeError(f"No natural key defined for {type(subject).__name__}")

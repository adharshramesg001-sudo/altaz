"""Deterministic analysis stage (LLD Section 5, nodes N4-N9).

Everything in this package is deterministic and evidence-grade by
construction -- no LLM calls, no confidence scores (parser output is ground
truth or explicitly marked `parse_failed` / `dynamic_unresolved`). Domain
agents (`atlaz.agents.*`) read this package's output; they never re-derive
it independently.
"""

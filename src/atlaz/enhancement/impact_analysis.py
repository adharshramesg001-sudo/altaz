"""Impact analysis over AtlaZ's own Neo4j knowledge graph -- this is the
"graph network path" a run already built (LLD Section 11), not a fresh
NetworkX dependency graph rebuilt per request the way a from-scratch tool
would. `Capability.member_modules` and each finding's `evidence_json` give
us the file set directly; a one-hop `Component -[:DEPENDS_ON]-> Component`
walk widens it to downstream-impacted files, the same shape as walking
ancestors in an import graph but grounded in the real extracted graph.

Deterministic and LLM-free by design, mirroring the reasoning agent's DRIFT/
PRODUCT_SYNTHESIS modes (dedicated Cypher, no LLM-authored query) rather
than its QA mode: relevance is plain keyword overlap between the
enhancement request and each node's text properties -- the same spirit as a
keyword-matched initial file selection, just scored against real graph data
instead of a fresh per-request repo scan.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from atlaz.enhancement.models import ImpactAnalysisResult, ImpactedFile
from atlaz.reasoning.cypher_safety import ensure_read_only

QueryRunner = Callable[[str, dict], list[dict]]

_CANDIDATE_QUERY = """
MATCH (n)
WHERE n:BusinessCapability OR n:BusinessRule OR n:Requirement OR n:Table
   OR n:API OR n:File OR n:DomainConcept OR n:SecurityControl
RETURN labels(n) AS labels, n.name AS name, n.rule_id AS rule_id,
       n.function_ref AS function_ref, n.route AS route, n.term AS term,
       n.control_type AS control_type, n.path AS file_path,
       n.description AS description, n.inferred_behavior AS inferred_behavior,
       n.definition AS definition, n.detail AS detail,
       n.member_modules AS member_modules, n.evidence_json AS evidence_json
"""

_WIDEN_QUERY = """
MATCH (cap:BusinessCapability)-[:HAS_FEATURE]->(:Feature)-[:IMPLEMENTED_BY]->(svc:Service)
WHERE cap.name IN $capability_names
MATCH (svc)-[:DEPENDS_ON]->(dep:Service)<-[:IMPLEMENTED_BY]-(:Feature)<-[:HAS_FEATURE]-(dcap:BusinessCapability)
RETURN DISTINCT dcap.name AS capability_name, dcap.member_modules AS member_modules
"""

_STOPWORDS = {
    "the", "a", "an", "to", "of", "for", "and", "or", "in", "on", "with",
    "add", "new", "please", "should", "want", "need", "make", "so", "that",
    "this", "it", "be", "is", "are", "we", "our", "support", "feature",
}


def _tokenize(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in _STOPWORDS and len(w) > 2}


def _searchable_text(record: dict) -> str:
    parts = [
        record.get("name"), record.get("rule_id"), record.get("function_ref"),
        record.get("route"), record.get("term"),
        record.get("control_type"), record.get("description"),
        record.get("inferred_behavior"), record.get("definition"), record.get("detail"),
    ]
    return " ".join(str(p) for p in parts if p)


def _node_key(record: dict) -> str:
    for field_name in ("name", "rule_id", "function_ref", "route", "term", "control_type", "file_path"):
        value = record.get(field_name)
        if value:
            return str(value)
    return "unknown"


def _evidence_files(record: dict) -> list[str]:
    raw = record.get("evidence_json")
    if not raw:
        return []
    try:
        evidence = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return [e["file"] for e in evidence if isinstance(e, dict) and e.get("file")]


@dataclass(slots=True)
class _ScoredNode:
    record: dict
    score: int


class ImpactAnalysisAgent:
    def __init__(self, query_runner: QueryRunner) -> None:
        self.query_runner = query_runner

    def run(self, enhancement_request: str, limit: int = 15) -> ImpactAnalysisResult:
        request_tokens = _tokenize(enhancement_request)
        records = self.query_runner(ensure_read_only(_CANDIDATE_QUERY), {})

        scored: list[_ScoredNode] = []
        for record in records:
            overlap = len(request_tokens & _tokenize(_searchable_text(record)))
            if overlap > 0:
                scored.append(_ScoredNode(record, overlap))
        scored.sort(key=lambda s: s.score, reverse=True)
        top = scored[:limit]

        files: dict[str, ImpactedFile] = {}
        matched_nodes: list[str] = []
        capability_names: set[str] = set()

        for scored_node in top:
            record = scored_node.record
            labels = record.get("labels") or []
            key = _node_key(record)
            matched_nodes.append(key)

            found_files: set[str] = set()
            if "File" in labels and record.get("file_path"):
                found_files.add(record["file_path"])
            if "BusinessCapability" in labels:
                capability_names.add(key)
                found_files.update(record.get("member_modules") or [])
            found_files.update(_evidence_files(record))

            for f in found_files:
                impacted = files.setdefault(
                    f, ImpactedFile(file_path=f, reason=f"matches request via {key}", matched_node_labels=[])
                )
                for label in labels:
                    if label not in impacted.matched_node_labels:
                        impacted.matched_node_labels.append(label)

        if capability_names:
            widen_records = self.query_runner(
                ensure_read_only(_WIDEN_QUERY), {"capability_names": list(capability_names)}
            )
            for record in widen_records:
                for f in record.get("member_modules") or []:
                    if f not in files:
                        files[f] = ImpactedFile(
                            file_path=f,
                            reason=f"downstream of a service depending on {record.get('capability_name')}",
                            matched_node_labels=["BusinessCapability"],
                        )

        return ImpactAnalysisResult(
            matched_nodes=matched_nodes,
            files=list(files.values()),
            graph_context=[s.record for s in top],
        )

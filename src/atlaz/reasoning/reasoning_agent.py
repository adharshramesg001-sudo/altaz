"""Core Reasoning Agent (LLD Section 12).

One agent, five modes, all reading from Neo4j -- not five separate agents.
QA/ENHANCEMENT/MODERNIZATION map a natural-language question to Cypher via
the LLM (schema-aware prompt, `ensure_read_only`-guarded before it ever
runs); DRIFT and PRODUCT_SYNTHESIS use the LLD's own dedicated Cypher
patterns directly, since both are structurally different from a free-form
lookup. The LLM never queries Neo4j with free-form text in any mode.

`query_runner` is injected (a `Callable[[str, dict], list[dict]]`) so this
class is fully testable against canned Cypher results without a live
database; `Neo4jReasoningStore.run` is the real implementation used in
production.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from atlaz.llm.client import BaseLLMClient
from atlaz.reasoning.cypher_safety import UnsafeCypherError, ensure_read_only

QueryRunner = Callable[[str, dict], list[dict]]

# Corners with a named place in the architecture but not built this cycle
# (HLD v2 Section 3) -- a question touching these gets an explicit
# "not yet extracted" notice rather than a confident-sounding non-answer.
UNBUILT_CORNERS = {
    "brd": "Business Requirements (BRD) -- conditional/workflow logic, architecture-only per HLD v2",
    "prd": "Product Requirements (PRD) inference from UI routes/feature flags -- architecture-only per HLD v2",
}

_SCHEMA_SUMMARY = """
Technical graph: Repository(repo_id, name, primary_languages),
Service(service_id, name, boundary_source, architecture_style) -- folder/
component boundary, doubles as the LLD's Module container, File(file_id,
path, language, classification), Class(class_id, name, file_id), Method
(method_id, name, file_id, reachability), Table(table_id, name, source_kind,
fields_json, tier, confidence), Database(database_id, name), API(api_id,
route, method, handler_ref, spec_source, tier, confidence).
Business graph: BusinessCapability(capability_id, name, cohesion_score,
tier, confidence, strategic_context_gap), Feature(feature_id, name,
confidence), Workflow(workflow_id, name, confidence), Step(step_id, name,
sequence_order), BusinessRule(rule_id, description, literal_value, status,
tier, confidence), DomainConcept(concept_id, term, definition,
occurrence_count, tier, confidence), Gap(gap_id, category, status,
signal_found, still_open).
Codebase-specific extensions: Requirement(function_ref, inferred_behavior,
tier, confidence), TestCase(name, file_path), SecurityControl(control_id,
control_type, location, detail, regulation_hypothesis, tier, confidence).
Relationship types: CONTAINS, DEFINES, CALLS, READS, WRITES, EXPOSES,
INVOKES, OWNS, BELONGS_TO, DEPENDS_ON, HAS_FEATURE, HAS_WORKFLOW, HAS_STEP,
GOVERNED_BY, USES, RELATES_TO, HAS_GAP, IMPLEMENTED_BY, REALIZED_BY,
EXECUTES, IMPLEMENTS, VALIDATES, CONFLICTS_WITH, DERIVED_FROM.
""".strip()

_CYPHER_SCHEMA = {"type": "object", "properties": {"cypher": {"type": "string"}}, "required": ["cypher"]}
_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer_text": {"type": "string"}, "confidence": {"type": "number"}},
    "required": ["answer_text", "confidence"],
}


class ReasoningMode(str, Enum):
    QA = "qa"
    ENHANCEMENT = "enhancement"
    MODERNIZATION = "modernization"
    DRIFT = "drift"
    PRODUCT_SYNTHESIS = "product_synthesis"


@dataclass(slots=True)
class AnsweredQuery:
    answer_text: str
    cited_nodes: list[str] = field(default_factory=list)
    confidence: float = 0.0
    gaps_encountered: list[str] = field(default_factory=list)


_DRIFT_QUERY = """
MATCH (rule:BusinessRule)-[c:CONFLICTS_WITH]->(impl:Table)
WHERE rule.repo_id = $repo_id
RETURN rule.rule_id AS rule_id, rule.literal_value AS rule_value,
       labels(impl) AS impl_labels, impl.name AS entity_name,
       c.field_name AS field_name, c.rule_value AS conflict_rule_value,
       c.table_value AS conflict_entity_value, c.status AS status,
       c.unresolved AS unresolved
"""

_PRODUCT_SYNTHESIS_QUERY = """
MATCH (cap:BusinessCapability)
WHERE cap.repo_id = $repo_id
OPTIONAL MATCH (cap)-[:HAS_FEATURE]->(feat:Feature)-[:IMPLEMENTED_BY]->(svc:Service)
OPTIONAL MATCH (svc)-[:OWNS]->(table:Table)
OPTIONAL MATCH (mod:File)-[:IMPLEMENTS]->(req:Requirement)
WHERE mod.repo_id = $repo_id
OPTIONAL MATCH (term:DomainConcept)
WHERE term.repo_id = $repo_id
RETURN cap.name AS capability, collect(DISTINCT svc.name) AS services,
       collect(DISTINCT table.name) AS tables,
       collect(DISTINCT req.inferred_behavior) AS requirements,
       collect(DISTINCT term.term) AS vocabulary
"""


class ReasoningAgent:
    def __init__(self, llm_client: BaseLLMClient, query_runner: QueryRunner) -> None:
        self.llm_client = llm_client
        self.query_runner = query_runner

    def answer(self, question: str, mode: ReasoningMode, repo_id: str) -> AnsweredQuery:
        gaps_encountered = self._gaps_mentioned_in(question)

        if mode == ReasoningMode.DRIFT:
            records = self.query_runner(_DRIFT_QUERY, {"repo_id": repo_id})
        elif mode == ReasoningMode.PRODUCT_SYNTHESIS:
            records = self.query_runner(_PRODUCT_SYNTHESIS_QUERY, {"repo_id": repo_id})
        else:
            records = self._run_generated_query(question, mode, repo_id)

        return self._synthesize(question, mode, records, gaps_encountered)

    def _gaps_mentioned_in(self, question: str) -> list[str]:
        lowered = question.lower()
        return [note for key, note in UNBUILT_CORNERS.items() if key in lowered]

    def _run_generated_query(self, question: str, mode: ReasoningMode, repo_id: str) -> list[dict]:
        prompt = (
            f"Knowledge graph schema:\n{_SCHEMA_SUMMARY}\n\n"
            f"Question ({mode.value} mode): {question}\n\n"
            "Write a single read-only Cypher query (MATCH/OPTIONAL MATCH/WITH/UNWIND/RETURN only, "
            "no CREATE/MERGE/DELETE/SET/CALL) that retrieves the graph data needed to answer this "
            "question, using only the labels/properties/relationship types listed above.\n\n"
            f"IMPORTANT: this Neo4j database holds multiple ingested repositories side by side. "
            f"This question is about exactly one of them, repo_id = '{repo_id}'. Every node label "
            f"above carries a `repo_id` property. Your query MUST add a `repo_id = '{repo_id}'` "
            "filter (via WHERE, inline in the MATCH pattern, or both) on every node variable you "
            "match, so it never reads another repository's data."
        )
        result = self.llm_client.complete_json(prompt, schema=_CYPHER_SCHEMA)
        cypher = result.get("cypher", "")
        try:
            safe_cypher = ensure_read_only(cypher)
        except UnsafeCypherError:
            return []  # treated as "no data retrieved" -- surfaces as a low-confidence answer, never executed
        try:
            return self.query_runner(safe_cypher, {"repo_id": repo_id})
        except Exception:  # noqa: BLE001 - a malformed but "safe-looking" query must not crash the caller
            return []

    def _synthesize(
        self, question: str, mode: ReasoningMode, records: list[dict], gaps_encountered: list[str]
    ) -> AnsweredQuery:
        if not records and not gaps_encountered:
            return AnsweredQuery(
                answer_text="No matching data was found in the knowledge graph for this question.",
                confidence=0.0,
            )

        prompt = (
            f"Question ({mode.value} mode): {question}\n\n"
            f"Retrieved graph records: {records}\n\n"
            "Using ONLY facts present in these records, write a concise, evidence-grounded answer. "
            "Do not introduce any claim -- about market, users, business justification, or anything else "
            "-- that these records do not support."
        )
        result = self.llm_client.complete_json(prompt, schema=_ANSWER_SCHEMA)
        answer_text = result.get("answer_text") or "The retrieved records could not be synthesized into an answer."
        try:
            confidence = float(result.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5
        confidence = max(0.0, min(1.0, confidence)) if records else 0.0

        cited_nodes = _extract_cited_node_keys(records)
        return AnsweredQuery(
            answer_text=answer_text,
            cited_nodes=cited_nodes,
            confidence=confidence,
            gaps_encountered=gaps_encountered,
        )


_CITABLE_FIELDS = (
    "rule_id", "entity_name", "capability", "capability_id", "route", "term", "concept_id",
    "function_ref", "feature_id", "workflow_id", "method_id", "class_id", "table_id", "api_id",
    "service_id", "file_id",
)


def _extract_cited_node_keys(records: list[dict]) -> list[str]:
    keys: list[str] = []
    for record in records:
        for key in _CITABLE_FIELDS:
            value = record.get(key)
            if value:
                keys.append(str(value))
    return sorted(set(keys))

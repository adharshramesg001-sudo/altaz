"""Reads every fact HLD/LLD generation needs out of the finished Neo4j
graph, via the same read-only `QueryRunner` shape `atlaz.reasoning` and
`atlaz.enhancement.impact_analysis` already use -- plain Cypher, no LLM,
each query scoped to one node/edge type from `graph_store.schema`.

Every query filters on `repo_id` (relationship queries filter both
endpoints). Neo4j here is one shared instance across every repo ever
ingested, and most node labels have no other run-scoping property --
without this filter, a document would silently blend facts from every
ingested repo together. See `Neo4jWriter.write_batch`'s docstring for how
`repo_id` gets stamped onto every node in the first place.
"""

from __future__ import annotations

from collections.abc import Callable

from atlaz.docgen.models import (
    ApiFact,
    BusinessRuleFact,
    CapabilityFact,
    ClassFact,
    ConflictFact,
    DomainConceptFact,
    GapFact,
    MethodFact,
    ProjectFacts,
    RepositoryFact,
    RequirementFact,
    SecurityControlFact,
    ServiceDependency,
    ServiceFact,
    TableFact,
    WorkflowFact,
)
from atlaz.reasoning.cypher_safety import ensure_read_only

QueryRunner = Callable[[str, dict], list[dict]]

_METHOD_LIMIT = 1000
_REQUIREMENT_LIMIT = 300
_CONCEPT_LIMIT = 40


def _run(query_runner: QueryRunner, cypher: str, params: dict) -> list[dict]:
    return query_runner(ensure_read_only(cypher), params)


def fetch_project_facts(query_runner: QueryRunner, thread_id: str, repo_id: str) -> ProjectFacts:
    p = {"repo_id": repo_id}

    repo_rows = _run(
        query_runner,
        "MATCH (r:Repository {repo_id: $repo_id}) RETURN r.repo_id AS repo_id, r.name AS name, r.primary_languages AS primary_languages LIMIT 1",
        p,
    )
    repository = (
        RepositoryFact(repo_id=repo_rows[0]["repo_id"] or "", name=repo_rows[0]["name"] or "", primary_languages=repo_rows[0]["primary_languages"] or [])
        if repo_rows
        else RepositoryFact(repo_id=repo_id, name=repo_id)
    )

    services = [
        ServiceFact(
            service_id=r["service_id"], name=r["name"], architecture_style=r.get("architecture_style") or "", module_count=r.get("module_count") or 0
        )
        for r in _run(
            query_runner,
            "MATCH (s:Service {repo_id: $repo_id}) RETURN s.service_id AS service_id, s.name AS name, "
            "s.architecture_style AS architecture_style, s.module_count AS module_count",
            p,
        )
    ]

    service_dependencies = [
        ServiceDependency(source=r["source"], target=r["target"], call_count=r.get("call_count") or 0)
        for r in _run(
            query_runner,
            "MATCH (a:Service {repo_id: $repo_id})-[d:DEPENDS_ON]->(b:Service {repo_id: $repo_id}) "
            "RETURN a.name AS source, b.name AS target, d.call_count AS call_count",
            p,
        )
    ]

    service_files: dict[str, list[str]] = {}
    for r in _run(
        query_runner,
        "MATCH (s:Service {repo_id: $repo_id})-[:CONTAINS]->(f:File {repo_id: $repo_id}) "
        "RETURN s.name AS service, f.path AS path ORDER BY s.name, f.path",
        p,
    ):
        service_files.setdefault(r["service"], []).append(r["path"])

    classes = [
        ClassFact(class_id=r["class_id"], name=r["name"], file_id=r["file_id"] or "", signature=r.get("signature") or "")
        for r in _run(
            query_runner,
            "MATCH (c:Class {repo_id: $repo_id}) RETURN c.class_id AS class_id, c.name AS name, c.file_id AS file_id, "
            "c.signature AS signature ORDER BY c.file_id, c.name",
            p,
        )
    ]

    methods = [
        MethodFact(
            method_id=r["method_id"], name=r["name"], file_id=r["file_id"] or "", signature=r.get("signature") or "",
            return_type=r.get("return_type") or "", reachability=r.get("reachability") or "unknown_external",
        )
        for r in _run(
            query_runner,
            "MATCH (m:Method {repo_id: $repo_id}) RETURN m.method_id AS method_id, m.name AS name, m.file_id AS file_id, "
            "m.signature AS signature, m.return_type AS return_type, m.reachability AS reachability "
            f"ORDER BY m.file_id, m.line_start LIMIT {_METHOD_LIMIT}",
            p,
        )
    ]

    file_classification_counts: dict[str, int] = {
        r["classification"]: r["count"]
        for r in _run(
            query_runner, "MATCH (f:File {repo_id: $repo_id}) RETURN f.classification AS classification, count(f) AS count", p
        )
    }

    capability_rows = _run(
        query_runner,
        "MATCH (bc:BusinessCapability {repo_id: $repo_id}) RETURN bc.capability_id AS capability_id, bc.name AS name, "
        "bc.confidence AS confidence, bc.cohesion_score AS cohesion_score, bc.member_modules AS member_modules, "
        "bc.needs_review AS needs_review",
        p,
    )
    feature_edges = _run(
        query_runner,
        "MATCH (bc:BusinessCapability {repo_id: $repo_id})-[:HAS_FEATURE]->(f:Feature {repo_id: $repo_id}) "
        "RETURN bc.name AS capability, f.feature_id AS feature_id",
        p,
    )
    features_by_capability: dict[str, list[str]] = {}
    for row in feature_edges:
        features_by_capability.setdefault(row["capability"], []).append(row["feature_id"])
    capabilities = [
        CapabilityFact(
            capability_id=r["capability_id"], name=r["name"], confidence=r.get("confidence") or 0.0,
            cohesion_score=r.get("cohesion_score") or 0.0, member_modules=r.get("member_modules") or [],
            needs_review=bool(r.get("needs_review")), feature_ids=features_by_capability.get(r["name"], []),
        )
        for r in capability_rows
    ]

    workflow_rows = _run(
        query_runner,
        "MATCH (w:Workflow {repo_id: $repo_id}) RETURN w.workflow_id AS workflow_id, w.name AS name, w.confidence AS confidence",
        p,
    )
    workflow_feature = {
        r["workflow_id"]: r["feature_id"]
        for r in _run(
            query_runner,
            "MATCH (f:Feature {repo_id: $repo_id})-[:HAS_WORKFLOW]->(w:Workflow {repo_id: $repo_id}) "
            "RETURN f.feature_id AS feature_id, w.workflow_id AS workflow_id",
            p,
        )
    }
    step_rows = _run(
        query_runner,
        "MATCH (w:Workflow {repo_id: $repo_id})-[:HAS_STEP]->(s:Step {repo_id: $repo_id}) "
        "RETURN w.workflow_id AS workflow_id, s.name AS step_name, s.sequence_order AS seq ORDER BY w.workflow_id, seq",
        p,
    )
    steps_by_workflow: dict[str, list[str]] = {}
    for row in step_rows:
        steps_by_workflow.setdefault(row["workflow_id"], []).append(row["step_name"])
    workflows = [
        WorkflowFact(
            workflow_id=r["workflow_id"], name=r["name"], confidence=r.get("confidence") or 0.0,
            feature_id=workflow_feature.get(r["workflow_id"], ""), steps=steps_by_workflow.get(r["workflow_id"], []),
        )
        for r in workflow_rows
    ]

    business_rules = [
        BusinessRuleFact(
            rule_id=r["rule_id"], description=r.get("description") or "", literal_value=r.get("literal_value") or "",
            source_kind=r.get("source_kind") or "", status=r.get("status") or "confirmed",
            confidence=r.get("confidence") or 0.0, needs_review=bool(r.get("needs_review")),
        )
        for r in _run(
            query_runner,
            "MATCH (br:BusinessRule {repo_id: $repo_id}) RETURN br.rule_id AS rule_id, br.description AS description, "
            "br.literal_value AS literal_value, br.source_kind AS source_kind, br.status AS status, "
            "br.confidence AS confidence, br.needs_review AS needs_review",
            p,
        )
    ]

    table_rows = _run(
        query_runner,
        "MATCH (t:Table {repo_id: $repo_id}) RETURN t.table_id AS table_id, t.name AS name, t.source_kind AS source_kind, "
        "t.fields_json AS fields_json, t.confidence AS confidence",
        p,
    )
    table_rel_rows = _run(
        query_runner,
        "MATCH (a:Table {repo_id: $repo_id})-[d:DEPENDS_ON]->(b:Table {repo_id: $repo_id}) "
        "RETURN a.name AS source, b.name AS target, d.kind AS kind",
        p,
    )
    relationships_by_table: dict[str, list[tuple[str, str, str]]] = {}
    for row in table_rel_rows:
        relationships_by_table.setdefault(row["source"], []).append((row["target"], row.get("kind") or "", row["target"]))
    tables = [
        TableFact(
            table_id=r["table_id"], name=r["name"], source_kind=r.get("source_kind") or "",
            fields_json=r.get("fields_json") or "[]", confidence=r.get("confidence") or 0.0,
            relationships=relationships_by_table.get(r["name"], []),
        )
        for r in table_rows
    ]

    apis = [
        ApiFact(
            api_id=r["api_id"], route=r["route"], method=r["method"], handler_ref=r.get("handler_ref"),
            spec_source=r.get("spec_source") or "", confidence=r.get("confidence") or 0.0,
        )
        for r in _run(
            query_runner,
            "MATCH (a:API {repo_id: $repo_id}) RETURN a.api_id AS api_id, a.route AS route, a.method AS method, "
            "a.handler_ref AS handler_ref, a.spec_source AS spec_source, a.confidence AS confidence",
            p,
        )
    ]

    security_controls = [
        SecurityControlFact(
            control_id=r["control_id"], control_type=r["control_type"], location=r.get("location") or "",
            detail=r.get("detail") or "", regulation_hypothesis=r.get("regulation_hypothesis"),
            regulation_confidence=r.get("regulation_confidence"),
        )
        for r in _run(
            query_runner,
            "MATCH (sc:SecurityControl {repo_id: $repo_id}) RETURN sc.control_id AS control_id, sc.control_type AS control_type, "
            "sc.location AS location, sc.detail AS detail, sc.regulation_hypothesis AS regulation_hypothesis, "
            "sc.regulation_confidence AS regulation_confidence",
            p,
        )
    ]

    domain_concepts = [
        DomainConceptFact(concept_id=r["concept_id"], term=r["term"], definition=r.get("definition") or "", occurrence_count=r.get("occurrence_count") or 0)
        for r in _run(
            query_runner,
            "MATCH (dc:DomainConcept {repo_id: $repo_id}) RETURN dc.concept_id AS concept_id, dc.term AS term, "
            f"dc.definition AS definition, dc.occurrence_count AS occurrence_count ORDER BY dc.occurrence_count DESC LIMIT {_CONCEPT_LIMIT}",
            p,
        )
    ]

    gaps = [
        GapFact(
            gap_id=r["gap_id"], category=r.get("category") or "business_case", status=r.get("status") or "external_only",
            signal_found=bool(r.get("signal_found")), still_open=bool(r.get("still_open", True)),
        )
        for r in _run(
            query_runner,
            "MATCH (g:Gap {repo_id: $repo_id}) RETURN g.gap_id AS gap_id, g.category AS category, g.status AS status, "
            "g.signal_found AS signal_found, g.still_open AS still_open",
            p,
        )
    ]

    requirements = [
        RequirementFact(
            function_ref=r["function_ref"], signature=r.get("signature") or "", inferred_behavior=r.get("inferred_behavior") or "",
            confidence=r.get("confidence") or 0.0, tier=r.get("tier") or "inferable",
        )
        for r in _run(
            query_runner,
            "MATCH (req:Requirement {repo_id: $repo_id}) RETURN req.function_ref AS function_ref, req.signature AS signature, "
            "req.inferred_behavior AS inferred_behavior, req.confidence AS confidence, req.tier AS tier "
            f"LIMIT {_REQUIREMENT_LIMIT}",
            p,
        )
    ]

    conflicts = [
        ConflictFact(
            rule_id=r["rule_id"], table_name=r["table_name"], status=r.get("status") or "unresolved_written_both",
            field_name=r.get("field_name") or "", rule_value=str(r.get("rule_value") or ""), table_value=str(r.get("table_value") or ""),
        )
        for r in _run(
            query_runner,
            "MATCH (r:BusinessRule {repo_id: $repo_id})-[c:CONFLICTS_WITH]->(t:Table {repo_id: $repo_id}) "
            "RETURN r.rule_id AS rule_id, t.name AS table_name, c.status AS status, c.field_name AS field_name, "
            "c.rule_value AS rule_value, c.table_value AS table_value",
            p,
        )
    ]

    return ProjectFacts(
        thread_id=thread_id,
        repository=repository,
        services=services,
        service_dependencies=service_dependencies,
        service_files=service_files,
        classes=classes,
        methods=methods,
        file_classification_counts=file_classification_counts,
        capabilities=capabilities,
        workflows=workflows,
        business_rules=business_rules,
        tables=tables,
        apis=apis,
        security_controls=security_controls,
        domain_concepts=domain_concepts,
        gaps=gaps,
        requirements=requirements,
        conflicts=conflicts,
    )

"""Groups a project's finished knowledge graph into migration units -- one
per `BusinessCapability` (the graph's own "cohesive slice of the system"
abstraction), falling back to one per `Service` when a repo has no
capabilities yet, and falling back further to a single whole-project unit
when it has neither. Each unit's `description` is rendered once here from
`ProjectFacts` and is the *entire* understanding `atlaz.migration.generator`
gets -- classes/methods are joined to a unit by `file_id` membership in its
files (`ClassFact.file_id`/`MethodFact.file_id` are literal file paths, see
`orchestration/nodes.py`'s `file_id=path`); business rules, tables, APIs,
and security controls carry no direct ownership edge to a capability or
service in the current schema, so they're joined by the same keyword-
overlap heuristic `atlaz.enhancement.impact_analysis` uses for relevance,
via `atlaz.shared.keyword_match`. When `repo_path` is given, each unit's
description is also augmented with static/technical values scanned from its
own files (`technical_values.py`) and the literal response field names its
own code's API handlers return (`api_response_shape.py`, also stored
structured on `MigrationUnit.known_response_fields` so `service.py` can
verify generation preserved them, not just hope the prompt worked) --
optional, and skipped entirely (not an error) when `repo_path` is omitted,
e.g. in tests that only exercise the fact-shaping logic.

`build_infra_unit()` is a separate entry point, not part of
`build_migration_units()`'s capability/service/project fallback chain: the
infra/build unit is generation-grounded differently (see
`infra_generator.py` -- it's the one unit type shown the real file content),
so its description here only lists file paths; `service.py` appends it to
the unit list itself.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from atlaz.docgen.models import CapabilityFact, ProjectFacts, ServiceFact
from atlaz.migration.api_response_shape import extract_response_field_names
from atlaz.migration.models import MigrationUnit
from atlaz.migration.technical_values import extract_static_values
from atlaz.shared.keyword_match import overlap_score

_RELATED_LIMIT = 8
_METHOD_DISPLAY_LIMIT = 40


def build_migration_units(facts: ProjectFacts, repo_path: str | None = None) -> list[MigrationUnit]:
    if facts.capabilities:
        return [_capability_unit(cap, facts, repo_path) for cap in facts.capabilities]
    if facts.services:
        return [_service_unit(svc, facts, repo_path) for svc in facts.services]
    return [_whole_project_unit(facts)]


def build_infra_unit(infra_file_paths: list[str]) -> MigrationUnit | None:
    if not infra_file_paths:
        return None
    paths = sorted(infra_file_paths)
    lines = ["Infrastructure/build files (real current content is shown at generation time):"]
    lines += [f"- {path}" for path in paths]
    return MigrationUnit(
        unit_id="infra", unit_type="infra", name="Infrastructure & build", description="\n".join(lines),
        file_paths=paths,
    )


def _capability_unit(cap: CapabilityFact, facts: ProjectFacts, repo_path: str | None) -> MigrationUnit:
    member_files = set(cap.member_modules)
    classes = [c for c in facts.classes if c.file_id in member_files]
    methods = [m for m in facts.methods if m.file_id in member_files]
    workflows = [w for w in facts.workflows if w.feature_id in cap.feature_ids]

    lines = [f"Business capability: {cap.name} (confidence {cap.confidence:.2f})"]
    if member_files:
        lines.append("Files: " + ", ".join(sorted(member_files)))
    lines += _class_and_method_lines(classes, methods)
    for wf in workflows:
        steps = " -> ".join(wf.steps) if wf.steps else "(no steps recorded)"
        lines.append(f"Workflow '{wf.name}': {steps}")
    lines += _related_fact_lines(cap.name, facts)
    lines += _static_value_lines(repo_path, member_files)
    response_fields = _response_fields(repo_path, member_files)
    lines += _response_field_lines(response_fields)

    return MigrationUnit(
        unit_id=cap.capability_id, unit_type="capability", name=cap.name, description="\n".join(lines),
        known_response_fields=response_fields,
    )


def _service_unit(svc: ServiceFact, facts: ProjectFacts, repo_path: str | None) -> MigrationUnit:
    member_files = set(facts.service_files.get(svc.name, []))
    classes = [c for c in facts.classes if c.file_id in member_files]
    methods = [m for m in facts.methods if m.file_id in member_files]
    depends_on = [d.target for d in facts.service_dependencies if d.source == svc.name]

    lines = [f"Service: {svc.name} (architecture: {svc.architecture_style or 'unknown'})"]
    if member_files:
        lines.append("Files: " + ", ".join(sorted(member_files)))
    if depends_on:
        lines.append("Depends on services: " + ", ".join(depends_on))
    lines += _class_and_method_lines(classes, methods)
    lines += _related_fact_lines(svc.name, facts)
    lines += _static_value_lines(repo_path, member_files)
    response_fields = _response_fields(repo_path, member_files)
    lines += _response_field_lines(response_fields)

    return MigrationUnit(
        unit_id=svc.service_id, unit_type="service", name=svc.name, description="\n".join(lines),
        known_response_fields=response_fields,
    )


def _static_value_lines(repo_path: str | None, member_files: set[str]) -> list[str]:
    if not repo_path or not member_files:
        return []
    values = extract_static_values(repo_path, sorted(member_files))
    if not values:
        return []
    lines = ["Static/technical values found in these files:"]
    lines += [f"- {v.name} = {v.value} ({v.file_path}:{v.line})" for v in values]
    return lines


def _response_fields(repo_path: str | None, member_files: set[str]) -> list[str]:
    if not repo_path or not member_files:
        return []
    return extract_response_field_names(repo_path, sorted(member_files))


def _response_field_lines(response_fields: list[str]) -> list[str]:
    if not response_fields:
        return []
    return [
        "Response field names observed in this unit's original code -- any API/response you "
        "generate MUST use exactly these field names (do not rename, drop, or add fields) unless "
        "the request explicitly asks for a different API surface: " + ", ".join(response_fields)
    ]


def _whole_project_unit(facts: ProjectFacts) -> MigrationUnit:
    name = facts.repository.name or facts.repository.repo_id or "project"
    languages = ", ".join(facts.repository.primary_languages) or "unknown language"
    lines = [
        f"Repository: {name} ({languages})",
        f"{len(facts.classes)} classes, {len(facts.methods)} methods across the codebase.",
    ]
    lines += _related_fact_lines(name, facts, limit=_RELATED_LIMIT * 2)

    return MigrationUnit(
        unit_id=facts.repository.repo_id or "project", unit_type="project", name=name, description="\n".join(lines)
    )


def _class_and_method_lines(classes, methods) -> list[str]:
    lines = []
    if classes:
        lines.append("Classes: " + ", ".join(f"{c.name} ({c.signature})" if c.signature else c.name for c in classes))
    if methods:
        shown = methods[:_METHOD_DISPLAY_LIMIT]
        lines.append("Methods: " + ", ".join(f"{m.name}{m.signature}" for m in shown))
    return lines


def _related_fact_lines(query_text: str, facts: ProjectFacts, limit: int = _RELATED_LIMIT) -> list[str]:
    lines: list[str] = []
    for rule in _related(query_text, facts.business_rules, lambda r: r.description, limit):
        detail = f" (value={rule.literal_value})" if rule.literal_value else ""
        lines.append(f"Business rule: {rule.description}{detail}")
    for table in _related(query_text, facts.tables, lambda t: t.name, limit):
        lines.append(f"Table {table.name}: fields={table.fields_json}")
    for api in _related(query_text, facts.apis, lambda a: f"{a.route} {a.handler_ref or ''}", limit):
        lines.append(f"API {api.method} {api.route} -> {api.handler_ref or 'unknown handler'}")
    for control in _related(
        query_text, facts.security_controls, lambda s: f"{s.control_type} {s.location} {s.detail}", limit
    ):
        lines.append(f"Security control: {control.control_type} at {control.location} -- {control.detail}")
    return lines


def _related(query_text: str, items: Iterable, key: Callable[[object], str], limit: int) -> list:
    scored = [(overlap_score(query_text, key(item)), item) for item in items]
    scored = [(score, item) for score, item in scored if score > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]

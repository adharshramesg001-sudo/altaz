"""Low-Level Design document generation -- entirely deterministic, no LLM
call anywhere in this module. Per the LLD's own confidence model, LLD-tier
facts (class/method signatures, data model fields, API contracts) are
near-ground-truth (confidence fixed at 1.0 for `LLDParser`'s own output);
narrating them through an LLM would only add a chance of drift from what
the graph actually says, for no benefit.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime

from atlaz.docgen.models import ProjectFacts


def generate_lld(facts: ProjectFacts) -> str:
    sections = [
        _header(facts),
        _module_breakdown(facts),
        _class_and_method_reference(facts),
        _data_model_detail(facts),
        _api_contract_detail(facts),
        _business_rule_detail(facts),
        _security_control_detail(facts),
        _functional_requirement_detail(facts),
        _conflict_detail(facts),
    ]
    return "\n\n".join(s for s in sections if s)


def _header(facts: ProjectFacts) -> str:
    generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"# Low-Level Design — {facts.repository.name or facts.thread_id}\n\n"
        f"| | |\n|---|---|\n"
        f"| **Source run** | `{facts.thread_id}` |\n"
        f"| **Generated** | {generated_at} |\n"
        f"| **Scope** | Class/method reference, data model, API contracts, business rules, "
        f"security controls — companion to the HLD, one level of detail deeper |"
    )


def _module_breakdown(facts: ProjectFacts) -> str:
    lines = ["## 1. Module / Service Breakdown", ""]
    if not facts.services:
        lines.append("_No service boundaries were derived from the codebase._")
        return "\n".join(lines)
    classes_by_file: dict[str, list[str]] = defaultdict(list)
    for c in facts.classes:
        classes_by_file[c.file_id].append(c.name)
    for s in sorted(facts.services, key=lambda s: s.name):
        lines.append(f"### `{s.name}` ({s.module_count} file(s))")
        lines.append("")
        for file_path in sorted(facts.service_files.get(s.name, [])):
            classes_here = classes_by_file.get(file_path, [])
            suffix = f" — {', '.join(sorted(classes_here))}" if classes_here else ""
            lines.append(f"- `{file_path}`{suffix}")
        lines.append("")
    return "\n".join(lines)


def _class_and_method_reference(facts: ProjectFacts) -> str:
    lines = ["## 2. Class & Method Reference", ""]
    if not facts.classes and not facts.methods:
        lines.append("_No classes or methods were parsed._")
        return "\n".join(lines)

    methods_by_class: dict[str, list] = defaultdict(list)
    standalone_functions: list = []
    class_ids = {c.class_id for c in facts.classes}
    for m in facts.methods:
        parent = m.method_id.rsplit(".", 1)[0]
        if parent in class_ids:
            methods_by_class[parent].append(m)
        else:
            standalone_functions.append(m)

    for c in sorted(facts.classes, key=lambda c: (c.file_id, c.name)):
        lines.append(f"### `{c.name}` — `{c.file_id}`")
        if c.signature:
            lines.append(f"```\n{c.signature}\n```")
        members = methods_by_class.get(c.class_id, [])
        if members:
            lines.append("")
            lines.append("| Method | Signature | Reachability |")
            lines.append("|---|---|---|")
            for m in sorted(members, key=lambda m: m.name):
                sig = m.signature or m.name
                lines.append(f"| {m.name} | `{sig}` | {m.reachability} |")
        lines.append("")

    if standalone_functions:
        lines.append("### Standalone functions")
        lines.append("")
        lines.append("| Function | File | Signature | Reachability |")
        lines.append("|---|---|---|---|")
        for m in sorted(standalone_functions, key=lambda m: (m.file_id, m.name)):
            sig = m.signature or m.name
            lines.append(f"| {m.name} | `{m.file_id}` | `{sig}` | {m.reachability} |")

    unreachable = [m for m in facts.methods if m.reachability == "unreachable"]
    if unreachable:
        lines.append("")
        lines.append(f"> **{len(unreachable)} method(s)** have no statically-resolved caller in this run (dead-code candidates, not a confirmed fact — dynamic dispatch is not resolved).")

    return "\n".join(lines)


def _data_model_detail(facts: ProjectFacts) -> str:
    lines = ["## 3. Data Model Detail", ""]
    if not facts.tables:
        lines.append("_No data entities were detected._")
        return "\n".join(lines)
    for t in sorted(facts.tables, key=lambda t: t.name):
        lines.append(f"### `{t.name}` ({t.source_kind}, confidence {t.confidence:.2f})")
        try:
            fields = json.loads(t.fields_json)
        except (TypeError, ValueError):
            fields = []
        if fields:
            lines.append("")
            lines.append("| Field | Type | Default |")
            lines.append("|---|---|---|")
            for f in fields:
                lines.append(f"| {f.get('name', '')} | {f.get('type') or 'unspecified'} | {f.get('default') if f.get('default') is not None else '—'} |")
        if t.relationships:
            lines.append("")
            lines.append("Relationships: " + ", ".join(f"→ `{target}` ({kind})" for target, kind, _ in t.relationships))
        lines.append("")
    return "\n".join(lines)


def _api_contract_detail(facts: ProjectFacts) -> str:
    lines = ["## 4. API Contract Detail", ""]
    if not facts.apis:
        lines.append("_No API contracts were detected._")
        return "\n".join(lines)
    for a in sorted(facts.apis, key=lambda a: (a.route, a.method)):
        lines.append(f"### {a.method} `{a.route}`")
        lines.append(f"- **Handler:** {a.handler_ref or 'unresolved'}")
        lines.append(f"- **Source:** {a.spec_source} (confidence {a.confidence:.2f})")
        lines.append("")
    return "\n".join(lines)


def _business_rule_detail(facts: ProjectFacts) -> str:
    lines = ["## 5. Business Rule Detail", ""]
    if not facts.business_rules:
        lines.append("_No business rules were extracted._")
        return "\n".join(lines)
    lines.append("| Rule ID | Description | Value | Source | Status | Confidence |")
    lines.append("|---|---|---|---|---|---|")
    for r in sorted(facts.business_rules, key=lambda r: r.rule_id):
        lines.append(f"| `{r.rule_id}` | {r.description} | `{r.literal_value}` | {r.source_kind} | {r.status} | {r.confidence:.2f} |")
    return "\n".join(lines)


def _security_control_detail(facts: ProjectFacts) -> str:
    lines = ["## 6. Security Control Detail", ""]
    if not facts.security_controls:
        lines.append("_No security controls were detected._")
        return "\n".join(lines)
    lines.append("| Type | Location | Detail | Regulation hypothesis |")
    lines.append("|---|---|---|---|")
    for c in sorted(facts.security_controls, key=lambda c: (c.control_type, c.location)):
        lines.append(f"| {c.control_type} | `{c.location}` | {c.detail} | {c.regulation_hypothesis or '—'} |")
    return "\n".join(lines)


def _functional_requirement_detail(facts: ProjectFacts) -> str:
    lines = ["## 7. Functional Requirements (sample)", ""]
    if not facts.requirements:
        lines.append("_No functional requirements were extracted._")
        return "\n".join(lines)
    lines.append("| Function | Behavior | Tier | Confidence |")
    lines.append("|---|---|---|---|")
    for r in sorted(facts.requirements, key=lambda r: r.function_ref)[:100]:
        lines.append(f"| `{r.function_ref}` | {r.inferred_behavior} | {r.tier} | {r.confidence:.2f} |")
    if len(facts.requirements) > 100:
        lines.append("")
        lines.append(f"_...and {len(facts.requirements) - 100} more (truncated for document length)._")
    return "\n".join(lines)


def _conflict_detail(facts: ProjectFacts) -> str:
    if not facts.conflicts:
        return ""
    lines = ["## 8. Cross-Domain Conflicts", "", "Rule-vs-implementation value mismatches, per the auto-resolve dispute policy:", ""]
    lines.append("| Rule | Table | Field | Rule value | Implemented value | Status |")
    lines.append("|---|---|---|---|---|---|")
    for c in facts.conflicts:
        lines.append(f"| `{c.rule_id}` | `{c.table_name}` | {c.field_name} | `{c.rule_value}` | `{c.table_value}` | {c.status} |")
    return "\n".join(lines)

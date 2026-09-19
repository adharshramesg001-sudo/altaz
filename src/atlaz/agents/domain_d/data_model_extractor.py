"""Data Model Extractor Agent (LLD Section 8.3, Corner #15).

ORM models are found by scanning classes for known base-class / decorator
patterns and reading field declarations directly from the AST. Migration
files are parsed as a secondary, corroborating source for entities not
represented in current ORM code. Relationships are derived from
foreign-key-shaped field expressions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from atlaz.ingestion.models import RepoInventory
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

ORM_BASE_CLASS_PATTERNS = {"Base", "models.Model", "db.Model", "Model", "declarative_base"}
ORM_DECORATOR_PATTERNS = {"Entity", "entity"}
FOREIGN_KEY_CALL_PATTERN = re.compile(r"\b(ForeignKey|relationship|ManyToOne|OneToMany|ManyToMany)\s*\(")
FOREIGN_KEY_TARGET_PATTERN = re.compile(r"""["']([A-Za-z_][\w\.]*)["']""")

# Required/optional heuristics -- pattern matching over the annotation text
# and the raw right-hand-side expression, not a real type-system evaluation.
# Covers the common conventions across the ORM/decorator patterns already
# recognized above (SQLAlchemy `nullable=`, Django `null=`/`blank=`,
# Pydantic `Field(...)` ellipsis-required, plain literal/`None` defaults).
_OPTIONAL_ANNOTATION_PATTERN = re.compile(r"Optional\[|(?:^|[\s\[])None(?:\s*\||\s*\]|\s*$)")
_NULLABLE_KWARG_PATTERN = re.compile(r"\b(?:nullable|null|blank)\s*=\s*(True|False)")
_REQUIRED_ELLIPSIS_PATTERN = re.compile(r"\bField\s*\(\s*\.\.\.")

_CREATE_TABLE = re.compile(r"CREATE\s+TABLE\s+(?:IF NOT EXISTS\s+)?[`\"\[]?(\w+)[`\"\]]?\s*\(", re.IGNORECASE)
_ALTER_TABLE = re.compile(r"ALTER\s+TABLE\s+[`\"\[]?(\w+)[`\"\]]?", re.IGNORECASE)
_COLUMN_LINE = re.compile(r"^\s*[`\"\[]?(\w+)[`\"\]]?\s+([A-Za-z][\w()]*)", re.MULTILINE)
_SQL_KEYWORDS = {
    "primary",
    "foreign",
    "constraint",
    "key",
    "unique",
    "index",
    "check",
    "references",
}


@dataclass(slots=True)
class FieldInfo:
    name: str
    field_type: str | None = None
    constraints: list[str] = field(default_factory=list)
    default_value: str | None = None  # plain literal default, when the field's value_expr is one (not a call)
    required: bool = True  # best-effort heuristic -- see _infer_required()


@dataclass(slots=True)
class EntityRelationship:
    from_entity: str
    to_entity: str
    kind: str  # "foreign_key" | "many_to_one" | "one_to_many" | "many_to_many"


@dataclass(slots=True)
class DataEntity:
    entity_name: str
    fields: list[FieldInfo] = field(default_factory=list)
    source_kind: str = "orm_model"  # "orm_model" | "migration" | "raw_sql_schema"
    relationships: list[EntityRelationship] = field(default_factory=list)
    tier: Tier = Tier.EXTRACTABLE
    confidence: float = 1.0
    evidence: list[Evidence] = field(default_factory=list)


class DataModelExtractor:
    def run(self, inventory: RepoInventory, parsed: list[ParsedModule]) -> list[DataEntity]:
        entities: dict[str, DataEntity] = {}

        for module in parsed:
            for cls in module.classes:
                if not _looks_like_orm_model(cls.base_classes, cls.decorators):
                    continue
                fields, relationships = _fields_and_relationships(cls.name, cls.fields)
                entities[cls.name] = DataEntity(
                    entity_name=cls.name,
                    fields=fields,
                    source_kind="orm_model",
                    relationships=relationships,
                    evidence=[Evidence(file=module.file_path, line=cls.line_start)],
                )

        for migration_entity in self._scan_migrations(inventory):
            if migration_entity.entity_name not in entities:
                entities[migration_entity.entity_name] = migration_entity
            else:
                entities[migration_entity.entity_name].source_kind = "orm_model"  # ORM takes precedence

        return list(entities.values())

    def _scan_migrations(self, inventory: RepoInventory) -> list[DataEntity]:
        candidates = [
            f
            for f in inventory.files
            if f.path.endswith(".sql") or "migration" in f.path.lower()
        ]
        found: list[DataEntity] = []
        for file_record in candidates:
            try:
                with open(inventory.abs_path(file_record.path), encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue

            for match in _CREATE_TABLE.finditer(content):
                table = match.group(1)
                line = content.count("\n", 0, match.start()) + 1
                body_end = _find_matching_paren(content, match.end() - 1)
                body = content[match.end() : body_end] if body_end else ""
                found.append(
                    DataEntity(
                        entity_name=table,
                        fields=_parse_sql_columns(body),
                        source_kind="raw_sql_schema",
                        evidence=[Evidence(file=file_record.path, line=line)],
                    )
                )
        return found

    @staticmethod
    def entity_derivation_edges(entities: list[DataEntity]) -> list[tuple[str, str]]:
        """entity_name pairs where a `derived_from` edge should link a
        migration-only entity to its later ORM counterpart of the same name --
        exposed for the graph writer (Section 11)."""
        by_source: dict[str, list[DataEntity]] = {}
        for e in entities:
            by_source.setdefault(e.entity_name, []).append(e)
        return [
            (e.entity_name, e.entity_name)
            for group in by_source.values()
            if len(group) > 1
            for e in group
            if e.source_kind == "raw_sql_schema"
        ]


def _looks_like_orm_model(base_classes: list[str], decorators: list[str]) -> bool:
    for base in base_classes:
        if any(pattern in base for pattern in ORM_BASE_CLASS_PATTERNS):
            return True
    for decorator in decorators:
        decorator_name = decorator.lstrip("@").split("(", 1)[0]
        if decorator_name in ORM_DECORATOR_PATTERNS:
            return True
    return False


def _fields_and_relationships(entity_name: str, raw_fields) -> tuple[list[FieldInfo], list[EntityRelationship]]:
    fields: list[FieldInfo] = []
    relationships: list[EntityRelationship] = []
    for raw in raw_fields:
        field_type = raw.annotation
        constraints: list[str] = []
        default_value = _plain_literal(raw.value_expr)

        fk_match = FOREIGN_KEY_CALL_PATTERN.search(raw.value_expr or "")
        if fk_match:
            kind_raw = fk_match.group(1)
            kind = {
                "ForeignKey": "foreign_key",
                "relationship": "foreign_key",
                "ManyToOne": "many_to_one",
                "OneToMany": "one_to_many",
                "ManyToMany": "many_to_many",
            }.get(kind_raw, "foreign_key")
            constraints.append(kind_raw)
            target_match = FOREIGN_KEY_TARGET_PATTERN.search(raw.value_expr or "")
            target = target_match.group(1).split(".")[0] if target_match else "unknown"
            relationships.append(EntityRelationship(from_entity=entity_name, to_entity=target, kind=kind))
            field_type = field_type or kind_raw

        fields.append(
            FieldInfo(
                name=raw.name,
                field_type=field_type,
                constraints=constraints,
                default_value=default_value,
                required=_infer_required(field_type, raw.value_expr, default_value),
            )
        )
    return fields, relationships


def _infer_required(field_type: str | None, value_expr: str | None, default_value: str | None) -> bool:
    """Best-effort required/optional heuristic (see module docstring for the
    patterns it covers). Defaults to True (required) when nothing says
    otherwise -- matching how a bare `name: str` field with no default
    behaves in Pydantic/dataclasses."""
    if field_type and _OPTIONAL_ANNOTATION_PATTERN.search(field_type):
        return False
    if value_expr:
        nullable_match = _NULLABLE_KWARG_PATTERN.search(value_expr)
        if nullable_match:
            return nullable_match.group(1) == "False"
        if _REQUIRED_ELLIPSIS_PATTERN.search(value_expr):
            return True
        if value_expr.strip() == "None":
            return False
    return default_value is None


_PLAIN_LITERAL_PATTERN = re.compile(r"^(\"[^\"]*\"|'[^']*'|-?\d+(?:\.\d+)?)$")


def _plain_literal(value_expr: str | None) -> str | None:
    if value_expr is None:
        return None
    stripped = value_expr.strip()
    if _PLAIN_LITERAL_PATTERN.match(stripped):
        return stripped.strip("\"'")
    return None


def _find_matching_paren(content: str, open_paren_index: int) -> int | None:
    depth = 0
    for i in range(open_paren_index, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return None


def _parse_sql_columns(body: str) -> list[FieldInfo]:
    fields = []
    for line in body.split(","):
        stripped_line = line.strip()
        match = _COLUMN_LINE.match(stripped_line)
        if not match:
            continue
        name, col_type = match.group(1), match.group(2)
        if name.lower() in _SQL_KEYWORDS:
            continue
        upper_line = stripped_line.upper()
        required = "NOT NULL" in upper_line or "PRIMARY KEY" in upper_line
        fields.append(FieldInfo(name=name, field_type=col_type, required=required))
    return fields

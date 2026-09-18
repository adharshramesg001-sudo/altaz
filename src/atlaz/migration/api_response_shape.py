"""Scans a migration unit's own files for the literal field names a
response payload actually returns -- deterministic, no LLM. Fixes a
concrete, observed failure mode: `atlaz.migration.generator`'s prompt
previously gave the LLM a route/method list (`API GET /infer -> handler`)
but never the *shape* of what that route returns, so generation would
invent a plausible-looking response (renaming `label`/`score`/
`model_version` to `sentiment`/`confidence`, dropping `model_version`
entirely) with nothing to check it against.

`agents.domain_d.api_contract_parser.APIContractParser` already has a
`response_schema` field on `APIContract`, but it's only ever populated from
an OpenAPI/Swagger spec file -- the route-decorator path (what a bare
FastAPI/Flask app without a spec file uses, i.e. the common case) never
infers a response shape from the handler's own code. This fills that gap,
migration-time, the same way `technical_values.py` does: not a general
Python/JS analyzer, deliberately narrow (a literal `return {...}` dict, or
a `dict(...)`/`jsonify(...)` call with keyword arguments) -- if the handler
builds its response through a variable, a helper, or a typed model class,
no fields are found. No fields is safer than wrong fields: this never
invents a schema it didn't literally see.
"""

from __future__ import annotations

import re
from pathlib import Path

from atlaz.enhancement.models import FileValidation
from atlaz.migration.models import GeneratedUnit, MigrationUnit

_RETURN_DICT_RE = re.compile(r"return\s*\{([^{}]*)\}", re.DOTALL)
_CALL_KWARGS_RE = re.compile(r"\b(?:dict|jsonify|JSONResponse)\s*\(([^()]*)\)")
_DICT_KEY_RE = re.compile(r"""["']([A-Za-z_][A-Za-z0-9_]*)["']\s*:""")
_KWARG_KEY_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=(?!=)")

_UNIT_LIMIT = 40


def extract_response_field_names(repo_path: str, file_paths: list[str]) -> list[str]:
    fields: set[str] = set()
    for file_path in file_paths:
        if len(fields) >= _UNIT_LIMIT:
            break
        try:
            content = (Path(repo_path) / file_path).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for match in _RETURN_DICT_RE.finditer(content):
            fields.update(_DICT_KEY_RE.findall(match.group(1)))
        for match in _CALL_KWARGS_RE.finditer(content):
            fields.update(_KWARG_KEY_RE.findall(match.group(1)))

    return sorted(fields)[:_UNIT_LIMIT]


def flag_missing_response_fields(
    units: list[MigrationUnit], generated_units: list[GeneratedUnit], validations: list[FileValidation]
) -> list[FileValidation]:
    """Deterministic post-generation check, not just a hopeful prompt: for
    every unit whose original code had known response fields, confirm each
    one still appears (literal substring match -- a heuristic, same spirit
    as `validator.py`'s regex checks, not a real parser) somewhere in that
    unit's generated output. A field silently renamed or dropped -- exactly
    the observed failure this whole module exists to catch -- gets flagged
    on every file in the unit, not swallowed as a clean pass.
    """
    units_by_id = {u.unit_id: u for u in units}
    validation_by_file = {v.file_path: v for v in validations}

    for gen_unit in generated_units:
        source_unit = units_by_id.get(gen_unit.unit_id)
        if not source_unit or not source_unit.known_response_fields or not gen_unit.files:
            continue
        combined_content = "\n".join(f.content for f in gen_unit.files)
        missing = [field for field in source_unit.known_response_fields if field not in combined_content]
        if not missing:
            continue

        warning = (
            "Response field(s) present in the original code were not found anywhere in this unit's "
            f"generated output: {', '.join(missing)}. Verify these weren't silently renamed or dropped."
        )
        for generated_file in gen_unit.files:
            validation = validation_by_file.get(generated_file.file_path)
            if validation:
                validation.warnings.append(warning)
            else:
                validation = FileValidation(file_path=generated_file.file_path, syntax_valid=True, warnings=[warning])
                validations.append(validation)
                validation_by_file[generated_file.file_path] = validation

    return validations

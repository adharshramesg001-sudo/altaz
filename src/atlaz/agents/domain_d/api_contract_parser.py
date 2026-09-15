"""API Contract Parser Agent (LLD Section 8.4, Corner #16).

If an OpenAPI/Swagger spec exists it is parsed directly (highest-confidence
source). Otherwise, route decorators/handlers are found via
`ParsedModule.decorators` and matched back to the handler's `LLDEntry` via
`handler_ref` -- this is what lets the reasoning layer answer "which
function implements this endpoint" without a second lookup pass.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from atlaz.ingestion.models import RepoInventory
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships with most stacks but stay defensive
    yaml = None

_OPENAPI_FILENAMES = re.compile(r"(openapi|swagger)[^/]*\.(ya?ml|json)$", re.IGNORECASE)

# decorator -> (http_method, route_arg_index_or_kwarg)
_ROUTE_DECORATOR_PATTERNS = [
    (re.compile(r"^app\.route\((.*)\)$"), None),  # Flask: method comes from methods=[...] kwarg, default GET
    (re.compile(r"^(?:app|router)\.(get|post|put|patch|delete)\((.*)\)$"), "group1"),
    (re.compile(r"^router\.(Get|Post|Put|Patch|Delete)\((.*)\)$"), "group1"),
]
_ROUTE_STRING_PATTERN = re.compile(r"""["']([^"']+)["']""")
_METHODS_KWARG_PATTERN = re.compile(r"methods\s*=\s*\[([^\]]*)\]")


@dataclass(slots=True)
class APIContract:
    route: str
    method: str
    handler_ref: str | None = None  # links to an LLDEntry.class_or_function
    request_schema: dict | None = None
    response_schema: dict | None = None
    source_kind: str = "route_decorator"  # "openapi_spec" | "route_decorator" | "proto_file"
    tier: Tier = Tier.EXTRACTABLE
    confidence: float = 1.0
    evidence: list[Evidence] = field(default_factory=list)


class APIContractParser:
    def run(self, inventory: RepoInventory, parsed: list[ParsedModule]) -> list[APIContract]:
        contracts = self._parse_openapi_specs(inventory)
        contracts.extend(self._parse_route_decorators(parsed))
        return contracts

    def _parse_openapi_specs(self, inventory: RepoInventory) -> list[APIContract]:
        contracts: list[APIContract] = []
        for file_record in inventory.files:
            if not _OPENAPI_FILENAMES.search(file_record.path):
                continue
            abs_path = inventory.abs_path(file_record.path)
            spec = _load_spec_file(abs_path)
            if not spec or "paths" not in spec:
                continue
            for route, methods in spec.get("paths", {}).items():
                if not isinstance(methods, dict):
                    continue
                for method, operation in methods.items():
                    if method.lower() not in {"get", "post", "put", "patch", "delete", "options", "head"}:
                        continue
                    operation = operation if isinstance(operation, dict) else {}
                    contracts.append(
                        APIContract(
                            route=route,
                            method=method.upper(),
                            handler_ref=operation.get("operationId"),
                            request_schema=_extract_request_schema(operation),
                            response_schema=_extract_response_schema(operation),
                            source_kind="openapi_spec",
                            evidence=[Evidence(file=file_record.path, line=1)],
                        )
                    )
        return contracts

    def _parse_route_decorators(self, parsed: list[ParsedModule]) -> list[APIContract]:
        contracts: list[APIContract] = []
        for module in parsed:
            for decorator_use in module.decorators:
                parsed_route = _parse_route_decorator(decorator_use.decorator)
                if parsed_route is None:
                    continue
                route, methods = parsed_route
                handler = decorator_use.target
                func = next((f for f in module.functions if f.qualified_name == handler), None)
                for method in methods:
                    contracts.append(
                        APIContract(
                            route=route,
                            method=method,
                            handler_ref=handler,
                            request_schema=_infer_request_schema_from_signature(func),
                            source_kind="route_decorator",
                            evidence=[Evidence(file=module.file_path, line=decorator_use.line)],
                        )
                    )
        return contracts


def _load_spec_file(abs_path: str) -> dict | None:
    path = Path(abs_path)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if path.suffix.lower() == ".json":
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    if yaml is not None:
        try:
            return yaml.safe_load(text)
        except Exception:  # noqa: BLE001 - malformed spec files should not crash the pipeline
            return None
    return None


def _extract_request_schema(operation: dict) -> dict | None:
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return None
    content = body.get("content", {})
    for media in content.values():
        if isinstance(media, dict) and "schema" in media:
            return media["schema"]
    return None


def _extract_response_schema(operation: dict) -> dict | None:
    responses = operation.get("responses", {})
    for status in ("200", "201", "default"):
        response = responses.get(status)
        if isinstance(response, dict):
            content = response.get("content", {})
            for media in content.values():
                if isinstance(media, dict) and "schema" in media:
                    return media["schema"]
    return None


def _parse_route_decorator(decorator: str) -> tuple[str, list[str]] | None:
    for pattern, _ in _ROUTE_DECORATOR_PATTERNS:
        match = pattern.match(decorator.strip())
        if not match:
            continue
        groups = match.groups()
        if len(groups) == 1:
            args = groups[0]
            route_match = _ROUTE_STRING_PATTERN.search(args)
            if not route_match:
                continue
            methods_match = _METHODS_KWARG_PATTERN.search(args)
            if methods_match:
                methods = [
                    m.strip().strip("'\"").upper() for m in methods_match.group(1).split(",") if m.strip()
                ]
            else:
                methods = ["GET"]
            return route_match.group(1), methods
        method, args = groups
        route_match = _ROUTE_STRING_PATTERN.search(args)
        if not route_match:
            continue
        return route_match.group(1), [method.upper()]
    return None


def _infer_request_schema_from_signature(func) -> dict | None:
    if func is None or not func.parameters:
        return None
    properties = {p.name: {"type": p.annotation or "unknown"} for p in func.parameters if p.name != "self"}
    if not properties:
        return None
    return {"type": "object", "properties": properties}

"""Parses dependency manifests into `Dependency` facts -- deterministic,
format-specific, no LLM. v1 covers the three ecosystems this project can
actually exercise (pip/Poetry via `requirements.txt`/`pyproject.toml`, npm
via `package.json`); an unrecognized manifest filename is skipped rather
than guessed at. Adding another ecosystem (go.mod, pom.xml, Gemfile,
composer.json) means adding another `_parse_*` function and a filename
dispatch entry here -- nothing else in the migration flow needs to change.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from atlaz.migration.models import Dependency

_REQUIREMENTS_LINE = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*(==|>=|<=|~=|!=|>|<)?\s*([A-Za-z0-9_.\-]*)")
_POETRY_VERSION = re.compile(r"[\^~>=<! ]*([\w.\-]*)")


def scan_dependencies(repo_path: str, manifest_paths: list[str]) -> list[Dependency]:
    dependencies: list[Dependency] = []
    for manifest_path in manifest_paths:
        name = Path(manifest_path).name.lower()
        full_path = Path(repo_path) / manifest_path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        if name == "requirements.txt":
            dependencies.extend(_parse_requirements_txt(content, manifest_path))
        elif name == "pyproject.toml":
            dependencies.extend(_parse_pyproject_toml(content, manifest_path))
        elif name == "package.json":
            dependencies.extend(_parse_package_json(content, manifest_path))
    return dependencies


def _parse_requirements_txt(content: str, manifest_path: str) -> list[Dependency]:
    deps = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-")):
            continue
        match = _REQUIREMENTS_LINE.match(line)
        if not match:
            continue
        deps.append(
            Dependency(name=match.group(1), version=match.group(3) or "", ecosystem="pypi", manifest_path=manifest_path)
        )
    return deps


def _parse_pyproject_toml(content: str, manifest_path: str) -> list[Dependency]:
    try:
        data = tomllib.loads(content)
    except tomllib.TOMLDecodeError:
        return []

    deps: list[Dependency] = []
    pep621_deps = data.get("project", {}).get("dependencies", [])
    for entry in pep621_deps:
        if not isinstance(entry, str):
            continue
        match = _REQUIREMENTS_LINE.match(entry.strip())
        if match:
            deps.append(
                Dependency(name=match.group(1), version=match.group(3) or "", ecosystem="pypi", manifest_path=manifest_path)
            )

    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for name, spec in poetry_deps.items():
        if name.lower() == "python":
            continue
        version = spec if isinstance(spec, str) else str(spec.get("version", "")) if isinstance(spec, dict) else ""
        version_match = _POETRY_VERSION.match(version.strip())
        deps.append(
            Dependency(
                name=name, version=version_match.group(1) if version_match else "", ecosystem="pypi",
                manifest_path=manifest_path,
            )
        )
    return deps


def _parse_package_json(content: str, manifest_path: str) -> list[Dependency]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []

    deps = []
    for section in ("dependencies", "devDependencies"):
        for name, version in (data.get(section) or {}).items():
            if not isinstance(name, str) or not isinstance(version, str):
                continue
            deps.append(Dependency(name=name, version=version.lstrip("^~>=< "), ecosystem="npm", manifest_path=manifest_path))
    return deps

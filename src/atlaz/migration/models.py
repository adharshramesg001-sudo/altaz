"""Dataclasses for the full-project migration flow. `MigrationUnit.
description` is the *entire* grounding a generation call gets -- built once
from the knowledge graph (see `unit_builder.py`) and never paired with the
original file source, unlike `atlaz.enhancement.models.FileModification`
which always carries `original_content`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class MigrationUnit:
    unit_id: str
    unit_type: str  # "capability" | "service" | "project" | "infra"
    name: str
    description: str
    file_paths: list[str] = field(default_factory=list)  # populated for the "infra" unit only
    known_response_fields: list[str] = field(default_factory=list)  # observed in the original code's responses


@dataclass(slots=True)
class MigrationTask:
    unit_id: str
    title: str
    description: str
    target_files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class MigrationPlan:
    summary: str
    tasks: list[MigrationTask] = field(default_factory=list)
    target_language: str = ""
    same_language: bool = True


@dataclass(slots=True)
class StaticValue:
    name: str
    value: str
    file_path: str
    line: int


@dataclass(slots=True)
class Dependency:
    name: str
    version: str
    ecosystem: str  # "pypi" | "npm" | ...
    manifest_path: str


@dataclass(slots=True)
class DependencyMapping:
    current_name: str
    current_version: str
    current_ecosystem: str
    target_name: str
    target_version: str
    target_ecosystem: str
    justification: str
    same_language: bool = True
    verified: bool = False
    verification_note: str = ""


@dataclass(slots=True)
class GeneratedFile:
    file_path: str
    content: str


@dataclass(slots=True)
class GeneratedUnit:
    unit_id: str
    unit_type: str
    name: str
    task_description: str
    files: list[GeneratedFile] = field(default_factory=list)

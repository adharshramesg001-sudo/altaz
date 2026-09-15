"""Fan-out parsing across every file in a `RepoInventory` (LLD Section 9:
"fan-out to one parse_node per detected language, each resolving its parser
via the registry, running in parallel"). This module provides the
sequential building block the LangGraph nodes call per language; the
`orchestration` layer is what actually parallelizes across languages.
"""

from __future__ import annotations

import logging

from atlaz.ingestion.models import FileRecord, RepoInventory
from atlaz.parsing.models import ParsedModule
from atlaz.parsing.parser_registry import ParserRegistry

logger = logging.getLogger(__name__)


def parse_files(inventory: RepoInventory, files: list[FileRecord], registry: ParserRegistry) -> list[ParsedModule]:
    modules: list[ParsedModule] = []
    for file_record in files:
        if not file_record.language:
            continue
        parser = registry.resolve(file_record.language, file_path=file_record.path)
        try:
            modules.append(parser.parse_file(file_record, inventory.repo_root))
        except Exception as exc:  # noqa: BLE001 - a single bad file must not abort the whole run
            logger.warning("Failed to parse %s: %s", file_record.path, exc)
    return modules


def parse_inventory(inventory: RepoInventory, registry: ParserRegistry | None = None) -> list[ParsedModule]:
    """Parse every language-tagged file in the inventory. Convenience entry
    point for callers that don't need per-language fan-out control."""
    registry = registry or ParserRegistry()
    taggable_files = [f for f in inventory.files if f.language]
    return parse_files(inventory, taggable_files, registry)

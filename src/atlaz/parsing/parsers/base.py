"""ASTParser Protocol (LLD Section 4.2)."""

from __future__ import annotations

from typing import Protocol

from atlaz.ingestion.models import FileRecord
from atlaz.parsing.models import ParsedModule


class ASTParser(Protocol):
    def parse_file(self, file_record: FileRecord, repo_root: str) -> ParsedModule: ...


def read_source(file_record: FileRecord, repo_root: str) -> str:
    import os

    abs_path = os.path.join(repo_root, file_record.path)
    with open(abs_path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def module_qualified_name(file_path: str) -> str:
    """Best-effort dotted module path from a POSIX-relative file path."""
    without_ext = file_path.rsplit(".", 1)[0]
    return without_ext.replace("/", ".")

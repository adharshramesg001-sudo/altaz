from pathlib import Path

from atlaz.ingestion.models import FileRecord
from atlaz.parsing.models import ParseDepth
from atlaz.parsing.parsers.python_ast import PythonASTParser

SOURCE = '''
"""Module docstring."""
import os
from typing import Optional


RATE_LIMIT = 30  # requests per minute


class Widget:
    """A widget."""

    def __init__(self, name: str):
        self.name = name

    def render(self) -> Optional[str]:
        # renders the widget
        return helper(self.name)


def helper(value: str) -> str:
    return os.path.basename(value)
'''


def _parse(tmp_path: Path):
    (tmp_path / "widget.py").write_text(SOURCE)
    record = FileRecord(path="widget.py", language="python", size=len(SOURCE), last_modified=0.0)
    return PythonASTParser().parse_file(record, str(tmp_path))


def test_extracts_classes_and_methods(tmp_path: Path):
    module = _parse(tmp_path)
    assert module.parse_depth == ParseDepth.FULL_AST
    assert module.parse_error is None

    class_names = {c.name for c in module.classes}
    assert class_names == {"Widget"}

    method_names = {f.name for f in module.functions if f.is_method}
    assert method_names == {"__init__", "render"}

    top_level = {f.name for f in module.functions if not f.is_method}
    assert top_level == {"helper"}


def test_extracts_imports_and_calls(tmp_path: Path):
    module = _parse(tmp_path)
    imported = {i.imported for i in module.imports}
    assert "os" in imported
    assert "typing.Optional" in imported

    callees = {c.callee for c in module.calls}
    assert "helper" in callees
    assert "basename" in callees


def test_extracts_comments(tmp_path: Path):
    module = _parse(tmp_path)
    texts = [c.text for c in module.comments]
    assert any("renders the widget" in t for t in texts)
    assert any("requests per minute" in t for t in texts)


def test_syntax_error_is_captured_not_raised(tmp_path: Path):
    bad_source = "def broken(:\n    pass"
    (tmp_path / "broken.py").write_text(bad_source)
    record = FileRecord(path="broken.py", language="python", size=len(bad_source), last_modified=0.0)
    module = PythonASTParser().parse_file(record, str(tmp_path))
    assert module.parse_error is not None
    assert module.classes == []

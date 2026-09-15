from pathlib import Path

from atlaz.ingestion.models import FileRecord
from atlaz.parsing.models import ParseDepth
from atlaz.parsing.parsers.tree_sitter_ast import TreeSitterASTParser

JS_SOURCE = """
// computes the total price
function calculateTotal(items) {
    return items.reduce(sum, 0);
}

class OrderService {
    placeOrder(order) {
        return calculateTotal(order.items);
    }
}
"""

GO_SOURCE = """
package main

import "fmt"

func Add(a int, b int) int {
    return a + b
}

type Server struct {
    Name string
}
"""


def test_javascript_extracts_functions_classes_and_calls(tmp_path: Path):
    (tmp_path / "orders.js").write_text(JS_SOURCE)
    record = FileRecord(path="orders.js", language="javascript", size=len(JS_SOURCE), last_modified=0.0)
    module = TreeSitterASTParser("javascript").parse_file(record, str(tmp_path))

    assert module.parse_depth == ParseDepth.GRAMMAR_AST
    assert module.parse_error is None
    assert "calculateTotal" in {f.name for f in module.functions}
    assert "OrderService" in {c.name for c in module.classes}
    assert any("total price" in c.text for c in module.comments)


def test_go_extracts_functions_and_types(tmp_path: Path):
    (tmp_path / "server.go").write_text(GO_SOURCE)
    record = FileRecord(path="server.go", language="go", size=len(GO_SOURCE), last_modified=0.0)
    module = TreeSitterASTParser("go").parse_file(record, str(tmp_path))

    assert module.parse_depth == ParseDepth.GRAMMAR_AST
    assert "Add" in {f.name for f in module.functions}

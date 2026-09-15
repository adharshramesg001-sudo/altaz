from pathlib import Path

from atlaz.agents.domain_d.api_contract_parser import APIContractParser
from atlaz.ingestion.repo_ingestor import RepoIngestor
from atlaz.parsing.parser_registry import ParserRegistry
from atlaz.parsing.pipeline import parse_inventory

FLASK_SOURCE = '''
from flask import Flask

app = Flask(__name__)


@app.route("/orders", methods=["POST"])
def create_order(customer_id: int, total: float):
    return {}


@app.get("/orders/<id>")
def get_order(id: int):
    return {}
'''

OPENAPI_SPEC = """
openapi: 3.0.0
paths:
  /widgets:
    get:
      operationId: listWidgets
      responses:
        '200':
          content:
            application/json:
              schema:
                type: array
"""


def test_extracts_route_decorator_contracts(tmp_path: Path):
    (tmp_path / "app.py").write_text(FLASK_SOURCE)
    inventory = RepoIngestor().ingest(str(tmp_path))
    parsed = parse_inventory(inventory, ParserRegistry())

    contracts = APIContractParser().run(inventory, parsed)
    routes = {(c.route, c.method) for c in contracts}

    assert ("/orders", "POST") in routes
    assert ("/orders/<id>", "GET") in routes

    post_contract = next(c for c in contracts if c.route == "/orders" and c.method == "POST")
    assert post_contract.source_kind == "route_decorator"
    assert post_contract.handler_ref is not None and "create_order" in post_contract.handler_ref
    assert post_contract.request_schema is not None
    assert "customer_id" in post_contract.request_schema["properties"]


def test_extracts_openapi_spec_contracts(tmp_path: Path):
    (tmp_path / "openapi.yaml").write_text(OPENAPI_SPEC)
    inventory = RepoIngestor().ingest(str(tmp_path))
    parsed = parse_inventory(inventory, ParserRegistry())

    contracts = APIContractParser().run(inventory, parsed)
    spec_contracts = [c for c in contracts if c.source_kind == "openapi_spec"]

    assert len(spec_contracts) == 1
    assert spec_contracts[0].route == "/widgets"
    assert spec_contracts[0].method == "GET"
    assert spec_contracts[0].handler_ref == "listWidgets"

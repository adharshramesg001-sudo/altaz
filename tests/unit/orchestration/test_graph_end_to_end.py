import sqlite3
import uuid
from pathlib import Path
from typing import ClassVar

from langgraph.checkpoint.sqlite import SqliteSaver

from atlaz.graph_store.schema import NodeLabel
from atlaz.llm.client import MockLLMClient
from atlaz.orchestration.capability_registry import load_capability_registry
from atlaz.orchestration.graph import build_state_graph
from atlaz.orchestration.serde import build_checkpoint_serializer
from atlaz.shared.config import PipelineConfig

SAMPLE_REPO = '''
"""Order billing module."""


class BillingPlan:
    late_fee_rate: float = 0.045


def compute_late_fee(order_id: int) -> float:
    """Computes the late fee for an order."""
    return BillingPlan.late_fee_rate * 100
'''

SAMPLE_TEST = """
from billing import compute_late_fee


def test_compute_late_fee_is_positive():
    assert compute_late_fee(1) > 0
"""


class FakeWriter:
    """Records what would have been written instead of touching Neo4j."""

    written_nodes: ClassVar[list] = []
    written_edges: ClassVar[list] = []

    def ensure_schema(self):
        pass

    def write_batch(self, nodes, edges, repo_id=None):
        FakeWriter.written_nodes = list(nodes)
        FakeWriter.written_edges = list(edges)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        pass


class FakeVectorIndex:
    def ensure_collection(self, collection, dimension):
        pass

    def upsert(self, collection, point_id, vector, payload):
        pass

    def search(self, collection, vector, limit):
        return []


def _build_repo(tmp_path: Path) -> str:
    (tmp_path / "billing.py").write_text(SAMPLE_REPO)
    (tmp_path / "test_billing.py").write_text(SAMPLE_TEST)
    (tmp_path / "README.md").write_text("This tool exists to help finance teams because manual billing was error-prone.")
    return str(tmp_path)


def _build_app(config: PipelineConfig, llm_client):
    registry = load_capability_registry()
    graph = build_state_graph(
        config, llm_client, registry, writer_factory=lambda: FakeWriter(), vector_index_factory=lambda: FakeVectorIndex()
    )
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    return graph.compile(checkpointer=SqliteSaver(conn, serde=build_checkpoint_serializer()))


def test_pipeline_runs_end_to_end_with_hitl_disabled(tmp_path: Path):
    repo_path = _build_repo(tmp_path)
    config = PipelineConfig(hitl_enabled=False, confidence_threshold=0.6)
    app = _build_app(config, MockLLMClient())

    thread_id = str(uuid.uuid4())
    initial_state = {"run_id": thread_id, "repo_path": repo_path, "run_mode": "full", "changed_files": None}
    result = app.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})

    assert "__interrupt__" not in result  # HITL disabled -- auto-resolve handles everything inline
    assert result["domains"]["domain_a"]["flagged_gaps"][0].tier.value == "external_only"
    assert result["domains"]["domain_c"]["frd_claims"]  # FRD extracted for compute_late_fee
    assert result["domains"]["domain_b"]["business_rules"]  # late_fee_rate literal picked up

    node_labels = {n.label for n in FakeWriter.written_nodes}
    assert NodeLabel.GAP in node_labels
    assert NodeLabel.FILE in node_labels
    assert NodeLabel.REQUIREMENT in node_labels
    assert NodeLabel.METHOD in node_labels


def test_pipeline_pauses_at_hitl_gate_when_enabled(tmp_path: Path):
    repo_path = _build_repo(tmp_path)
    config = PipelineConfig(hitl_enabled=True, confidence_threshold=0.6)
    app = _build_app(config, MockLLMClient())

    thread_id = str(uuid.uuid4())
    initial_state = {"run_id": thread_id, "repo_path": repo_path, "run_mode": "full", "changed_files": None}
    result = app.invoke(initial_state, config={"configurable": {"thread_id": thread_id}})

    assert "__interrupt__" in result
    flagged = result["__interrupt__"][0].value
    assert any(item.kind.value == "gap_confirmation" for item in flagged)

    from langgraph.types import Command

    from atlaz.hitl.auto_resolve import auto_resolve

    resolutions = auto_resolve(flagged)
    final = app.invoke(Command(resume=resolutions), config={"configurable": {"thread_id": thread_id}})

    assert "__interrupt__" not in final
    assert FakeWriter.written_nodes  # write_knowledge_graph ran after resume

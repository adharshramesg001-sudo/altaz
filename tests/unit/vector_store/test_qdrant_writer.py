from atlaz.vector_store.qdrant_writer import (
    BUSINESS_RULE,
    NullVectorIndex,
    VectorDocument,
    resolve_candidates,
    write_documents,
)


class FakeVectorIndex:
    def __init__(self):
        self.collections: dict[str, int] = {}
        self.points: dict[str, list[tuple]] = {}

    def ensure_collection(self, collection, dimension):
        self.collections[collection] = dimension

    def upsert(self, collection, point_id, vector, payload):
        self.points.setdefault(collection, []).append((point_id, vector, payload))

    def search(self, collection, vector, limit):
        return [{"score": 0.9, **payload} for _, _, payload in self.points.get(collection, [])][:limit]


def _embed(text: str) -> list[float]:
    return [float(len(text))]


def test_write_documents_ensures_collection_once_and_upserts_with_prefix():
    index = FakeVectorIndex()
    docs = [
        VectorDocument(collection=BUSINESS_RULE, key="rule-1", text="late fee rule", payload={"rule_id": "rule-1"}),
        VectorDocument(collection=BUSINESS_RULE, key="rule-2", text="another rule", payload={"rule_id": "rule-2"}),
    ]

    written = write_documents(index, _embed, "atlaz", docs, dimension=4)

    assert written == 2
    assert index.collections == {"atlaz_business_rule_embeddings": 4}
    assert len(index.points["atlaz_business_rule_embeddings"]) == 2
    payloads = [p for _, _, p in index.points["atlaz_business_rule_embeddings"]]
    assert all(p["node_key"] in {"rule-1", "rule-2"} for p in payloads)


def test_same_key_produces_a_stable_point_id():
    index = FakeVectorIndex()
    doc = VectorDocument(collection=BUSINESS_RULE, key="rule-1", text="x", payload={})
    write_documents(index, _embed, "atlaz", [doc])
    write_documents(index, _embed, "atlaz", [doc])

    point_ids = {pid for pid, _, _ in index.points["atlaz_business_rule_embeddings"]}
    assert len(point_ids) == 1  # same (collection, key) -> same deterministic point id


def test_resolve_candidates_discards_hits_that_no_longer_exist_in_neo4j():
    index = FakeVectorIndex()
    write_documents(index, _embed, "atlaz", [VectorDocument(collection=BUSINESS_RULE, key="rule-1", text="x", payload={})])

    def query_runner(cypher, params):
        return []  # simulates a stale hit -- the node was deleted/re-run

    resolved = resolve_candidates(index, _embed, "atlaz", BUSINESS_RULE, "x", query_runner, "BusinessRule", "rule_id")
    assert resolved == []  # never surfaced as a dangling reference


def test_resolve_candidates_returns_hits_that_do_resolve():
    index = FakeVectorIndex()
    write_documents(index, _embed, "atlaz", [VectorDocument(collection=BUSINESS_RULE, key="rule-1", text="x", payload={})])

    def query_runner(cypher, params):
        assert params["key"] == "rule-1"
        return [{"rule_id": "rule-1"}]

    resolved = resolve_candidates(index, _embed, "atlaz", BUSINESS_RULE, "x", query_runner, "BusinessRule", "rule_id")
    assert len(resolved) == 1
    assert resolved[0]["node_key"] == "rule-1"


def test_null_vector_index_is_a_safe_no_op():
    index = NullVectorIndex()
    index.ensure_collection("c", 4)
    index.upsert("c", "1", [0.0], {})
    assert index.search("c", [0.0], 5) == []

from atlaz.enhancement.guideline_store import GuidelineRetrievalAgent, _fallback_embed, default_embed_fn
from atlaz.shared.config import LLMConfig


class FakeVectorIndex:
    """In-memory `VectorIndex` -- lets these tests exercise chunking, add,
    query, and the "already populated" guard without pymilvus installed."""

    def __init__(self):
        self.entries: list[tuple[str, list[float], dict]] = []

    def add(self, doc_id, vector, metadata):
        self.entries.append((doc_id, vector, metadata))

    def count(self) -> int:
        return len(self.entries)

    def search(self, vector, limit, category):
        def dist(vec):
            return sum((a - b) ** 2 for a, b in zip(vector, vec)) ** 0.5

        candidates = [e for e in self.entries if category is None or e[2].get("category") == category]
        candidates.sort(key=lambda e: dist(e[1]))
        return [{"score": dist(vec), **meta} for _, vec, meta in candidates[:limit]]


def _fake_embed(text: str) -> list[float]:
    return [float(len(text)), float(sum(ord(c) for c in text) % 997)]


def test_add_document_chunks_long_content():
    index = FakeVectorIndex()
    agent = GuidelineRetrievalAgent(index, _fake_embed)

    long_content = "x" * 2000
    agent.add_document("Big Doc", long_content, "coding_standards")

    assert index.count() > 1
    assert all(meta["category"] == "coding_standards" for _, _, meta in index.entries)


def test_query_returns_retrieved_guideline_dataclasses():
    index = FakeVectorIndex()
    agent = GuidelineRetrievalAgent(index, _fake_embed)
    agent.add_document("Naming", "use snake_case for python files", "coding_standards")

    hits = agent.query("naming convention question", limit=3)

    assert len(hits) == 1
    assert hits[0].title == "Naming"
    assert hits[0].category == "coding_standards"
    assert "snake_case" in hits[0].content


def test_populate_default_guidelines_is_a_noop_when_already_populated():
    index = FakeVectorIndex()
    index.add("existing", [0.0, 0.0], {"title": "t", "content": "c", "category": "x"})
    agent = GuidelineRetrievalAgent(index, _fake_embed)

    agent.populate_default_guidelines()

    assert index.count() == 1


def test_populate_default_guidelines_seeds_when_empty():
    index = FakeVectorIndex()
    agent = GuidelineRetrievalAgent(index, _fake_embed)

    agent.populate_default_guidelines()

    assert index.count() > 0
    categories = {meta["category"] for _, _, meta in index.entries}
    assert "security" in categories


def test_fallback_embed_is_deterministic_and_normalized():
    v1 = _fallback_embed("some guideline text")
    v2 = _fallback_embed("some guideline text")
    v3 = _fallback_embed("different text")

    assert v1 == v2
    assert v1 != v3
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_default_embed_fn_falls_back_for_mock_provider():
    embed_fn = default_embed_fn(LLMConfig(provider="mock"))
    assert embed_fn("hello") == _fallback_embed("hello")

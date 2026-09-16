"""Local vector store of enterprise coding/architecture/security guidelines
the code-modification step is instructed to follow -- the RAG half of a
Brownfield-style retrieval agent, reimplemented against AtlaZ's own
dependency-injection conventions: `VectorIndex` is injected exactly like
`QueryRunner` in `atlaz.reasoning` or `LLMClient` in `atlaz.llm`, so unit
tests never need `pymilvus` installed (see `tests/unit/enhancement` for the
in-memory fake used there).

Real embeddings are used only when the configured LLM provider is one
OpenAI's embeddings API actually serves (`openai`/`azure`); every other
provider -- including `mock`, this project's default and test double --
falls back to a deterministic seeded vector. That fallback exists to prove
the retrieval plumbing (chunk, embed, index, search) end to end without a
live embeddings endpoint; it does not pretend to be semantic search.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Protocol, runtime_checkable

from atlaz.enhancement.models import RetrievedGuideline
from atlaz.shared.config import LLMConfig

_DIMENSION = 1536
_CHUNK_SIZE = 800
_CHUNK_OVERLAP = 150


@runtime_checkable
class VectorIndex(Protocol):
    def add(self, doc_id: str, vector: list[float], metadata: dict) -> None: ...
    def search(self, vector: list[float], limit: int, category: str | None) -> list[dict]: ...
    def count(self) -> int: ...


class MilvusLiteVectorIndex:
    """Real `VectorIndex`, backed by an embedded Milvus Lite `.db` file --
    zero external service, same "just a local file" shape as this project's
    SQLite checkpoint store."""

    def __init__(self, db_path: str, collection_name: str, dimension: int = _DIMENSION) -> None:
        try:
            from pymilvus import MilvusClient
        except ImportError as exc:
            raise RuntimeError(
                "pymilvus is not installed; run `pip install atlaz[guidelines]` "
                "or set GUIDELINE_STORE_ENABLED=false"
            ) from exc

        self.collection_name = collection_name
        self.dimension = dimension
        self.client = MilvusClient(uri=db_path)
        if not self.client.has_collection(collection_name=collection_name):
            self.client.create_collection(
                collection_name=collection_name, dimension=dimension, id_type="string", max_length=64
            )

    def add(self, doc_id: str, vector: list[float], metadata: dict) -> None:
        self.client.insert(collection_name=self.collection_name, data=[{"id": doc_id, "vector": vector, **metadata}])

    def search(self, vector: list[float], limit: int, category: str | None) -> list[dict]:
        filter_expr = f'category == "{category}"' if category else ""
        results = self.client.search(
            collection_name=self.collection_name,
            data=[vector],
            limit=limit,
            filter=filter_expr,
            output_fields=["title", "content", "category"],
        )
        return [{"score": r["distance"], **r["entity"]} for r in results[0]]

    def count(self) -> int:
        return len(self.client.query(collection_name=self.collection_name, filter='category != ""', limit=1))


def default_embed_fn(config: LLMConfig) -> Callable[[str], list[float]]:
    """Real OpenAI/Azure embeddings when the pipeline's LLM provider is
    configured for one of them; a deterministic seeded fallback otherwise."""
    if config.provider in {"openai", "azure"} and config.api_key:
        try:
            import openai

            if config.provider == "azure":
                client = openai.AzureOpenAI(
                    api_key=config.api_key,
                    azure_endpoint=config.azure_endpoint,
                    api_version=config.azure_api_version or "2024-12-01-preview",
                )
            else:
                kwargs = {"api_key": config.api_key}
                if config.base_url:
                    kwargs["base_url"] = config.base_url
                client = openai.OpenAI(**kwargs)

            def _real_embed(text: str) -> list[float]:
                response = client.embeddings.create(input=[text], model="text-embedding-3-small")
                return response.data[0].embedding

            return _real_embed
        except ImportError:
            pass

    return _fallback_embed


def _fallback_embed(text: str) -> list[float]:
    import numpy as np

    rng = np.random.default_rng(abs(hash(text)) % (2**32 - 1))
    vector = rng.uniform(-1.0, 1.0, _DIMENSION)
    norm = np.linalg.norm(vector)
    if norm > 0:
        vector = vector / norm
    return vector.tolist()


_DEFAULT_GUIDELINES = [
    {
        "title": "Secure Coding Policy - APIs",
        "category": "security",
        "content": (
            "All APIs must validate and sanitize input. Never build SQL from raw string "
            "concatenation. Never log secrets, tokens, or credentials."
        ),
    },
    {
        "title": "Coding Standards",
        "category": "coding_standards",
        "content": (
            "Match the existing file's naming convention, indentation, and comment style. "
            "Keep changes scoped to exactly what the task requires; do not rewrite unrelated code."
        ),
    },
    {
        "title": "Modernization Boundaries",
        "category": "architecture",
        "content": (
            "UI talks only to the API layer; the API layer talks only to services; services own "
            "data access. Do not add direct database calls from UI or controller layers."
        ),
    },
]


class GuidelineRetrievalAgent:
    def __init__(self, index: VectorIndex, embed_fn: Callable[[str], list[float]]) -> None:
        self.index = index
        self.embed_fn = embed_fn

    def add_document(self, title: str, content: str, category: str) -> str:
        doc_id = str(uuid.uuid4())
        start, chunk_idx = 0, 0
        while start < len(content):
            end = min(start + _CHUNK_SIZE, len(content))
            chunk = content[start:end]
            self.index.add(
                f"{doc_id}_{chunk_idx}",
                self.embed_fn(chunk),
                {"title": title, "content": chunk, "category": category},
            )
            chunk_idx += 1
            if end == len(content):
                break
            start += _CHUNK_SIZE - _CHUNK_OVERLAP
        return doc_id

    def query(self, text: str, category: str | None = None, limit: int = 3) -> list[RetrievedGuideline]:
        hits = self.index.search(self.embed_fn(text), limit, category)
        return [
            RetrievedGuideline(
                title=h.get("title", ""), category=h.get("category", ""),
                content=h.get("content", ""), score=float(h.get("score", 0.0)),
            )
            for h in hits
        ]

    def populate_default_guidelines(self) -> None:
        if self.index.count() > 0:
            return
        for doc in _DEFAULT_GUIDELINES:
            self.add_document(doc["title"], doc["content"], doc["category"])

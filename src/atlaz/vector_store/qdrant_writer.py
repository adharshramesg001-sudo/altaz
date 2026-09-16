"""Qdrant vector index (LLD Section 10.1, 14.3, node N18
`write_vector_index`).

`VectorIndex` is injected exactly like `atlaz.enhancement.guideline_store`'s
`VectorIndex` Protocol -- unit tests never need `qdrant-client` installed.
Embeddings reuse `atlaz.enhancement.guideline_store.default_embed_fn`
directly (real OpenAI/Azure embeddings when configured, a deterministic
seeded fallback otherwise) rather than duplicating that logic.

**Candidate retrieval only, never authoritative** (LLD Section 14.3's
non-negotiable retrieval contract): `resolve_candidates` always resolves a
hit's `node_key` back to a real Neo4j node before returning it; a stale hit
(deleted entity, rebuilt index) is discarded silently, never surfaced as a
dangling reference.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

_DEFAULT_DIMENSION = 1536

# The five collections LLD Section 14.3 specifies.
CODE = "code_embeddings"
BUSINESS_RULE = "business_rule_embeddings"
FEATURE = "feature_embeddings"
GLOSSARY = "glossary_embeddings"
DOC = "doc_embeddings"


@runtime_checkable
class VectorIndex(Protocol):
    def ensure_collection(self, collection: str, dimension: int) -> None: ...
    def upsert(self, collection: str, point_id: str, vector: list[float], payload: dict) -> None: ...
    def search(self, collection: str, vector: list[float], limit: int) -> list[dict]: ...


class QdrantVectorIndex:
    """Real `VectorIndex`, backed by a Qdrant service (LLD's primary
    recommendation, per the user's explicit choice over a Neo4j-native
    vector index)."""

    def __init__(self, url: str, api_key: str | None = None, dimension: int = _DEFAULT_DIMENSION) -> None:
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:
            raise RuntimeError(
                "qdrant-client is not installed; run `pip install qdrant-client` or set QDRANT_ENABLED=false"
            ) from exc
        self.client = QdrantClient(url=url, api_key=api_key)
        self.dimension = dimension

    def ensure_collection(self, collection: str, dimension: int) -> None:
        from qdrant_client.models import Distance, VectorParams

        if not self.client.collection_exists(collection):
            self.client.create_collection(
                collection_name=collection, vectors_config=VectorParams(size=dimension, distance=Distance.COSINE)
            )

    def upsert(self, collection: str, point_id: str, vector: list[float], payload: dict) -> None:
        from qdrant_client.models import PointStruct

        self.client.upsert(collection_name=collection, points=[PointStruct(id=point_id, vector=vector, payload=payload)])

    def search(self, collection: str, vector: list[float], limit: int) -> list[dict]:
        if not self.client.collection_exists(collection):
            return []
        hits = self.client.query_points(collection_name=collection, query=vector, limit=limit).points
        return [{"score": h.score, **(h.payload or {})} for h in hits]


class NullVectorIndex:
    """No-op stand-in used when `QDRANT_ENABLED=false` or the client can't
    be constructed -- `write_vector_index` still runs (topology stays
    correct), it just writes nothing, mirroring the guideline store's
    "optional collaborator" shape."""

    def ensure_collection(self, collection: str, dimension: int) -> None:
        return None

    def upsert(self, collection: str, point_id: str, vector: list[float], payload: dict) -> None:
        return None

    def search(self, collection: str, vector: list[float], limit: int) -> list[dict]:
        return []


@dataclass(slots=True)
class VectorDocument:
    collection: str  # one of CODE/BUSINESS_RULE/FEATURE/GLOSSARY/DOC
    key: str  # the source graph node's natural key -- stored in payload as `node_key`
    text: str  # text to embed
    payload: dict


def write_documents(
    index: VectorIndex,
    embed_fn: Callable[[str], list[float]],
    collection_prefix: str,
    documents: list[VectorDocument],
    dimension: int = _DEFAULT_DIMENSION,
) -> int:
    ensured: set[str] = set()
    written = 0
    for doc in documents:
        collection = f"{collection_prefix}_{doc.collection}"
        if collection not in ensured:
            index.ensure_collection(collection, dimension)
            ensured.add(collection)
        vector = embed_fn(doc.text)
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{collection}:{doc.key}"))
        index.upsert(collection, point_id, vector, {**doc.payload, "node_key": doc.key})
        written += 1
    return written


def resolve_candidates(
    index: VectorIndex,
    embed_fn: Callable[[str], list[float]],
    collection_prefix: str,
    collection: str,
    query_text: str,
    query_runner: Callable[[str, dict], list[dict]],
    node_label: str,
    key_property: str,
    limit: int = 10,
) -> list[dict]:
    vector = embed_fn(query_text)
    hits = index.search(f"{collection_prefix}_{collection}", vector, limit)
    resolved: list[dict] = []
    for hit in hits:
        node_key = hit.get("node_key")
        if not node_key:
            continue
        records = query_runner(f"MATCH (n:{node_label} {{{key_property}: $key}}) RETURN n", {"key": node_key})
        if records:
            resolved.append({"score": hit.get("score"), "node_key": node_key, "record": records[0]})
    return resolved

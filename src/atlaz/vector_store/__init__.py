"""Vector index (LLD Section 10.1, 14.3) -- candidate retrieval only, never
authoritative. Every hit resolves to a Neo4j node before being trusted; see
`atlaz.vector_store.qdrant_writer` for the enforcement of that contract."""

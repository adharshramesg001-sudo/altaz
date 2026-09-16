"""HLD/LLD document generation from an already-ingested run's knowledge
graph. On-demand, like `atlaz.enhancement` -- reads the finished Neo4j
graph via `Neo4jReasoningStore`, never re-parses the repo. Deterministic
facts (services, classes, methods, data model, API surface, business
rules, security controls) are rendered directly from graph data; the LLM
is used only for the HLD's executive summary, explicitly instructed to
synthesize from the given facts and never invent business context the
graph doesn't support -- the same anti-fabrication discipline the rest of
AtlaZ's pipeline holds to.
"""

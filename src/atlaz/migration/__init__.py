"""Full-project migration flow: "migrate this to an entirely new stack,"
grounded entirely in the finished knowledge graph -- never in the original
file source. Deliberately separate from `atlaz.enhancement`, which patches
a keyword-matched subset of *existing* files in place: this flow pulls the
whole-project understanding (`atlaz.docgen.graph_facts.fetch_project_facts`,
the same fact assembly HLD/LLD generation uses), groups it into migration
units (one per business capability, or per service as a fallback), and
generates fresh code per unit from that understanding alone. Propose-only,
like `atlaz.enhancement` -- never writes back into the ingested repo.
"""

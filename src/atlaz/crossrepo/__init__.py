"""Cross-repo service correlation.

On-demand operation against two already-ingested runs: finds evidence that
a service in one repo calls a service in another and records it as a
`CALLS_SERVICE` edge in the shared Neo4j graph. See `CrossRepoLinkService`
in `atlaz.crossrepo.service` for the entry point.

Deliberately not a LangGraph node -- like `atlaz.docgen`/`atlaz.enhancement`,
this reads (and in this case also writes) against two finished runs' graphs,
not part of the per-repo ingestion pipeline.
"""

from __future__ import annotations

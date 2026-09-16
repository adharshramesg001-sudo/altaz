"""Enhancement/retrieval flow: given an already-ingested run and a natural-
language change request, find the files AtlaZ's own knowledge graph says are
relevant (`impact_analysis`), optionally ground the change in retrieved
enterprise guidelines (`guideline_store`), draft modified file content
(`modifier`), and write the result to a separate `outputs/` folder
(`output_writer`) -- never back into the ingested repository. `service`
wires all four into one call.

This is deliberately not a stage of the extraction pipeline in
`atlaz.orchestration`: it runs against a run's *already-written* graph, on
demand, with no HITL interrupt/resume semantics.
"""

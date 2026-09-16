"""AtlaZ Streamlit application -- two screens, Ingest and Retrieve &
Document (see `main.py`). Replaces the prior multi-page HITL review app:
there is no separate review screen here (`ingest.py` runs the three-tier
HITL gate auto-resolved, inline), and no code-modification screen (the
`atlaz enhance` CLI command still exists for that, just not surfaced here).
Nothing in this package exposes infrastructure configuration to the user --
every page reads `PipelineConfig.from_env()` silently.
"""

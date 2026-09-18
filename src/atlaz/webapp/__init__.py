"""AtlaZ Streamlit application -- a single scrolling page, three sections:
Ingest, Retrieve & Document, and Modernize (see `main.py`). Replaces the
prior multi-page HITL review app: there is no separate review screen here
(`ingest.py` runs the three-tier HITL gate auto-resolved, inline), and no
`st.navigation` -- the three sections stack vertically on one page, sharing
one project picker. Nothing in this package exposes infrastructure
configuration to the user -- every section reads `PipelineConfig.from_env()`
silently.
"""

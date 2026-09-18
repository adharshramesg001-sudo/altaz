"""Shared project-selection widget -- a dropdown over completed ingestion
runs, keyed by `repo_id`, never a thread_id the user has to type. Used by
every page that operates on an already-ingested project (Retrieve &
Document, Modernize) so the picker behaves identically everywhere.
"""

from __future__ import annotations

import streamlit as st

from atlaz.audit.models import PipelineRun


def select_project(runs: list[PipelineRun]) -> PipelineRun:
    labels = [f"{r.repo_id}  ·  {r.started_at:%Y-%m-%d %H:%M}" for r in runs]
    selected_thread_id = st.session_state.get("selected_thread_id")
    default_index = next((i for i, r in enumerate(runs) if r.thread_id == selected_thread_id), 0)
    choice = st.selectbox("Project", labels, index=default_index)
    run = runs[labels.index(choice)]
    st.session_state["selected_thread_id"] = run.thread_id
    return run

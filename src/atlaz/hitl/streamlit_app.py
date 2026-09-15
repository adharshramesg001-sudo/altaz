"""Streamlit Review App (LLD Section 10.2).

A separate process from the LangGraph pipeline; it communicates only
through the shared LangGraph checkpoint store (SQLite), so a reviewer can
close the browser and come back later without losing state. Renders every
flagged item in one queue -- gap confirmations, low-confidence findings,
conflicts -- and resumes the paused graph once every item in the queue has
a submitted resolution.

Run via `atlaz review <thread_id>` (wraps `streamlit run streamlit_app.py --
--thread-id <id>`), not by importing this module directly.
"""

from __future__ import annotations

import argparse
import sys

import streamlit as st

from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind, ReviewResolution
from atlaz.orchestration.runner import get_pending_review_items, resume_pipeline
from atlaz.shared.config import PipelineConfig


def _parse_thread_id() -> str:
    parser = argparse.ArgumentParser()
    parser.add_argument("--thread-id", required=True)
    args, _ = parser.parse_known_args(sys.argv[1:])
    return args.thread_id


def _render_gap_card(item: ReviewItem) -> ReviewResolution:
    st.markdown(f"**Gap confirmation** — {item.summary}")
    finding = item.subject
    if finding.candidate_signals:
        st.caption("Candidate signals found in the codebase (raw evidence, not a conclusion):")
        for signal in finding.candidate_signals[:10]:
            st.text(f"[{signal.source_kind}] {signal.text}  ({signal.evidence.file}:{signal.evidence.line})")
    else:
        st.caption("No code-adjacent signal was found for this corner.")

    answer = st.text_area(
        "Business context (paste an excerpt, a wiki link, or your own answer). Leave blank if unknown.",
        key=f"answer::{item.item_id}",
    )
    reviewer = st.session_state.get("reviewer_name", "")
    if answer.strip():
        return ReviewResolution(item_id=item.item_id, action=ReviewAction.ACCEPT, resolved_value=answer.strip(), reviewer=reviewer)
    return ReviewResolution(
        item_id=item.item_id, action=ReviewAction.REJECT, resolved_value=None, reviewer=reviewer,
        resolution_note="no info available",
    )


def _render_low_confidence_card(item: ReviewItem) -> ReviewResolution:
    st.markdown(f"**Low-confidence finding** — {item.summary}")
    st.caption(f"source: {item.source_domain}")
    action_label = st.radio(
        "Action", ["Accept as-is", "Reject (exclude from graph)"], key=f"action::{item.item_id}", horizontal=True
    )
    reviewer = st.session_state.get("reviewer_name", "")
    if action_label.startswith("Reject"):
        return ReviewResolution(item_id=item.item_id, action=ReviewAction.REJECT, reviewer=reviewer)
    return ReviewResolution(item_id=item.item_id, action=ReviewAction.ACCEPT, resolved_value=item.subject, reviewer=reviewer)


def _render_conflict_card(item: ReviewItem) -> ReviewResolution:
    conflict = item.subject
    st.markdown(f"**Conflict** — {item.summary}")
    choice = st.radio(
        "Which side reflects true current intent?",
        [f"Rule value ({conflict.rule_value})", f"Implemented value ({conflict.entity_value})", "Leave unresolved"],
        key=f"conflict::{item.item_id}",
        horizontal=True,
    )
    reviewer = st.session_state.get("reviewer_name", "")
    note = "left unresolved -- no side preferred" if choice == "Leave unresolved" else f"reviewer chose: {choice}"
    return ReviewResolution(
        item_id=item.item_id, action=ReviewAction.RESOLVE_CONFLICT, resolved_value=conflict,
        reviewer=reviewer, resolution_note=note,
    )


_RENDERERS = {
    ReviewItemKind.GAP_CONFIRMATION: _render_gap_card,
    ReviewItemKind.LOW_CONFIDENCE_FINDING: _render_low_confidence_card,
    ReviewItemKind.CONFLICT: _render_conflict_card,
}


def main() -> None:
    st.set_page_config(page_title="AtlaZ Review", layout="wide")
    thread_id = _parse_thread_id()
    config = PipelineConfig.from_env()

    st.title("AtlaZ — Human-in-the-Loop Review")
    st.caption(f"thread_id = {thread_id}")

    st.session_state.setdefault("reviewer_name", "")
    st.session_state["reviewer_name"] = st.text_input("Reviewer name/email", value=st.session_state["reviewer_name"])

    flagged: list[ReviewItem] = get_pending_review_items(thread_id, config)
    if not flagged:
        st.success("No pending review items for this run — it may already be complete, or the thread_id is unknown.")
        return

    st.write(f"{len(flagged)} item(s) awaiting review.")
    resolutions: list[ReviewResolution] = []
    for item in flagged:
        with st.expander(item.item_id, expanded=True):
            renderer = _RENDERERS[item.kind]
            resolutions.append(renderer(item))

    if st.button("Submit all resolutions and resume pipeline", type="primary"):
        with st.spinner("Resuming pipeline and writing to the knowledge graph..."):
            result = resume_pipeline(thread_id, resolutions, config)
        st.success(f"Pipeline resumed and completed. Nodes written: {len(result.state.get('graph_write_nodes', []))}")


if __name__ == "__main__":
    main()

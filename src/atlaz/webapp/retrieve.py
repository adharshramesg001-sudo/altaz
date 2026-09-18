"""Retrieve & Document page -- ask questions against an ingested project's
knowledge graph, and generate/download its HLD and LLD.

Project selection is a dropdown over completed ingestion runs (from the
Postgres audit trail), never a thread_id the user has to copy-paste. HLD/
LLD's `project_id` is derived automatically from the run's own `repo_id`
-- never typed by the user, so `outputs/<repo_id>/docs/...` stays stable
across regenerations of the same project. Nothing here is user-
configurable beyond the question itself and which project to look at.
"""

from __future__ import annotations

import streamlit as st

from atlaz.audit.models import PipelineRun
from atlaz.audit.repository import list_completed_runs
from atlaz.crossrepo.review import UnconfirmedLink, fetch_unconfirmed, set_status
from atlaz.docgen.graph_facts import fetch_project_facts
from atlaz.docgen.models import GapFact
from atlaz.docgen.service import DocumentationService
from atlaz.llm.client import build_llm_client
from atlaz.reasoning.neo4j_query_runner import Neo4jReasoningStore
from atlaz.reasoning.reasoning_agent import ReasoningAgent, ReasoningMode
from atlaz.shared.config import PipelineConfig
from atlaz.webapp import style
from atlaz.webapp.project_picker import select_project

_MODE_LABELS = {
    ReasoningMode.QA: "General question",
    ReasoningMode.PRODUCT_SYNTHESIS: "What does this product do? (overview)",
    ReasoningMode.DRIFT: "Where does intent diverge from implementation?",
    ReasoningMode.MODERNIZATION: "Modernization guidance",
    ReasoningMode.ENHANCEMENT: "Enhancement guidance",
}
_EXAMPLE_PLACEHOLDERS = {
    ReasoningMode.QA: "e.g. What does the billing module do?",
    ReasoningMode.PRODUCT_SYNTHESIS: "e.g. What does this product do?",
    ReasoningMode.DRIFT: "e.g. Where does intent diverge from implementation?",
    ReasoningMode.MODERNIZATION: "e.g. What would need to change to move this to microservices?",
    ReasoningMode.ENHANCEMENT: "e.g. How would I add rate limiting to checkout?",
}


def _heading() -> None:
    style.page_heading(
        "🔎 Retrieve & Document",
        "STEP 2",
        "Ask questions, review links AtlaZ inferred, and generate design docs for an ingested project.",
        anchor_id="retrieve",
    )


def render() -> None:
    """Standalone entry point -- picks its own project. `main.py`'s
    single-page layout calls `render_body()` instead, with a project already
    chosen by the shared picker above this section."""
    try:
        runs = list_completed_runs()
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        _heading()
        st.error(f"Couldn't reach the audit database: {exc}")
        return

    if not runs:
        _heading()
        st.info("No ingested projects yet. Use **Ingest** above to get started.")
        return

    render_body(select_project(runs))


def render_body(run: PipelineRun) -> None:
    _heading()
    ask_tab, docs_tab, review_tab, gaps_tab = st.tabs(
        ["💬 Ask a question", "📄 HLD & LLD", "🔗 Review links", "❓ Open questions"]
    )
    with ask_tab:
        _render_ask(run)
    with docs_tab:
        _render_docs(run)
    with review_tab:
        _render_review(run)
    with gaps_tab:
        _render_gaps(run)


def _render_ask(run: PipelineRun) -> None:
    mode = st.selectbox("What kind of question?", list(_MODE_LABELS), format_func=lambda m: _MODE_LABELS[m], key="ask_mode")
    question = st.text_area("Your question", placeholder=_EXAMPLE_PLACEHOLDERS[mode], key="ask_question")

    if st.button("Ask", type="primary", disabled=not question.strip()):
        config = PipelineConfig.from_env()
        with st.spinner("Thinking..."):
            try:
                llm_client = build_llm_client(config.llm)
                with Neo4jReasoningStore(config.neo4j) as store:
                    agent = ReasoningAgent(llm_client, store.run)
                    answer = agent.answer(question, mode, run.repo_id)
            except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
                st.error(f"Couldn't answer that: {exc}")
                return
        st.session_state[f"answer::{run.thread_id}"] = answer

    answer = st.session_state.get(f"answer::{run.thread_id}")
    if not answer:
        return

    st.divider()
    st.markdown(answer.answer_text)
    st.caption(f"Confidence: {answer.confidence:.2f}")
    if answer.cited_nodes:
        st.caption("Cited: " + ", ".join(answer.cited_nodes))
    for gap in answer.gaps_encountered:
        st.warning(gap)


def _render_docs(run: PipelineRun) -> None:
    st.caption("Generates a High-Level Design and Low-Level Design document from this project's knowledge graph.")

    cache_key = f"docs::{run.thread_id}"
    if st.button("Generate HLD & LLD", type="primary"):
        config = PipelineConfig.from_env()
        with st.spinner("Reading the knowledge graph and drafting documents..."):
            try:
                llm_client = build_llm_client(config.llm)
                with Neo4jReasoningStore(config.neo4j) as store:
                    service = DocumentationService(llm_client, store.run)
                    doc_result = service.run(run.thread_id, run.repo_id, save=True)
            except ValueError as exc:
                st.error(str(exc))
                return
        st.session_state[cache_key] = doc_result

    doc_result = st.session_state.get(cache_key)
    if not doc_result:
        return

    if doc_result.output_dir:
        st.caption(f"Saved to `{doc_result.output_dir}`")

    hld_tab, lld_tab = st.tabs(["HLD", "LLD"])
    with hld_tab:
        st.download_button("⬇ Download HLD.md", doc_result.hld_markdown, file_name="HLD.md", mime="text/markdown")
        st.markdown(doc_result.hld_markdown)
    with lld_tab:
        st.download_button("⬇ Download LLD.md", doc_result.lld_markdown, file_name="LLD.md", mime="text/markdown")
        st.markdown(doc_result.lld_markdown)


_LINK_KIND_LABEL = {"calls_service": "calls", "publishes": "publishes to", "consumes": "consumes from"}


def _render_review(run: PipelineRun) -> None:
    st.caption(
        "Cross-repo links AtlaZ inferred from source (synchronous calls and async messaging) that "
        "haven't been confirmed yet -- confirm or reject each one."
    )

    cache_key = f"review::{run.thread_id}"
    if st.button("🔄 Check for unconfirmed links", key=f"load_review_{run.thread_id}"):
        config = PipelineConfig.from_env()
        with st.spinner("Checking the graph..."):
            try:
                with Neo4jReasoningStore(config.neo4j) as store:
                    st.session_state[cache_key] = fetch_unconfirmed(store.run, run.repo_id)
            except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
                st.error(f"Couldn't reach the knowledge graph: {exc}")

    links: list[UnconfirmedLink] | None = st.session_state.get(cache_key)
    if links is None:
        return
    if not links:
        st.success("🎉 No unconfirmed links for this project.")
        return

    c1, c2 = st.columns(2)
    style.stat_card(c1, len(links), "Unconfirmed links", "warn")
    style.stat_card(c2, f"{min(link.confidence for link in links):.0%}", "Lowest confidence", "warn")
    st.write("")

    for link in links:
        with st.container(border=True):
            target_label = f"`{link.target_repo_id}:{link.target}`" if link.target_repo_id else f"topic `{link.target}`"
            st.markdown(
                f"{style.chip_html(link.kind, link.kind)} `{link.source_repo_id}:{link.source}` "
                f"**{_LINK_KIND_LABEL[link.kind]}** {target_label}",
                unsafe_allow_html=True,
            )
            progress_col, confirm_col, reject_col = st.columns([3, 1, 1])
            progress_col.progress(link.confidence, text=f"confidence {link.confidence:.0%} · {link.detail}")
            if confirm_col.button("✓ Confirm", key=f"confirm_{link.rel_id}", type="primary", width="stretch"):
                _resolve_link(run, link.rel_id, "confirmed", cache_key)
            if reject_col.button("✗ Reject", key=f"reject_{link.rel_id}", width="stretch"):
                _resolve_link(run, link.rel_id, "rejected", cache_key)


def _resolve_link(run: PipelineRun, rel_id: int, status: str, cache_key: str) -> None:
    config = PipelineConfig.from_env()
    try:
        with Neo4jReasoningStore(config.neo4j) as store:
            set_status(store.run, rel_id, status)
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not a crash
        st.error(f"Couldn't update the knowledge graph: {exc}")
        return
    st.session_state[cache_key] = [link for link in st.session_state[cache_key] if link.rel_id != rel_id]
    st.rerun()


def _render_gaps(run: PipelineRun) -> None:
    st.caption("Things the code can't answer on its own -- flagged instead of guessed.")

    cache_key = f"gaps::{run.thread_id}"
    if st.button("🔄 Check for open questions", key=f"load_gaps_{run.thread_id}"):
        config = PipelineConfig.from_env()
        with st.spinner("Reading the knowledge graph..."), Neo4jReasoningStore(config.neo4j) as store:
            facts = fetch_project_facts(store.run, run.thread_id, run.repo_id)
        st.session_state[cache_key] = facts.gaps

    gaps: list[GapFact] | None = st.session_state.get(cache_key)
    if gaps is None:
        return

    open_gaps = [gap for gap in gaps if gap.still_open]
    if not open_gaps:
        st.success("🎉 No open questions for this project.")
        return

    for gap in open_gaps:
        title = gap.category.replace("_", " ").title()
        signal = "a partial signal was found" if gap.signal_found else "no signal found in the code"
        st.markdown(
            f'<div class="gap-card"><b>{title}</b> {style.chip_html(gap.status)}<br>'
            f"AtlaZ can't infer this from code alone -- {signal}.</div>",
            unsafe_allow_html=True,
        )


if __name__ == "__main__":
    st.set_page_config(page_title="AtlaZ — Retrieve", page_icon="🔎", layout="wide")
    style.inject()
    render()

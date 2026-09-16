"""Shared visual styling for the Streamlit app -- one CSS injection call
from `main.py` before navigation runs, plus a couple of small reusable
render helpers (colored stat cards, chips) so `ingest.py`/`retrieve.py`
don't duplicate markup. Purely cosmetic: no data/query logic lives here.
"""

from __future__ import annotations

import streamlit as st

NAVY = "#16324F"
TEAL = "#1F7A8C"
AMBER = "#D99A00"
RED = "#C0392B"
GREEN = "#2E8B57"

_CSS = f"""
<style>
.block-container {{ padding-top: 1.6rem; }}
h1 {{ color: {NAVY}; }}

.atlaz-header {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 0.1rem; }}
.atlaz-header .badge {{
    background: {NAVY}; color: white; border-radius: 999px; padding: 2px 14px;
    font-size: 0.8rem; font-weight: 600; letter-spacing: 0.03em;
}}

.stat {{ background: white; border: 1px solid #E3E8EF; border-radius: 14px; padding: 16px 18px; }}
.stat .num {{ font-size: 1.9rem; font-weight: 700; color: {NAVY}; line-height: 1.15; }}
.stat .lbl {{ color: #5B6677; font-size: 0.85rem; margin-top: 2px; }}
.stat.warn .num {{ color: {AMBER}; }}
.stat.risk .num {{ color: {RED}; }}
.stat.good .num {{ color: {TEAL}; }}

.chip {{
    display: inline-block; background: #EEF3F8; color: {NAVY}; border-radius: 999px;
    padding: 3px 12px; margin: 0 6px 6px 0; font-size: 0.85rem;
}}
.chip.kind-calls_service {{ background: #E4F0F8; color: {TEAL}; }}
.chip.kind-publishes {{ background: #FBF1DC; color: {AMBER}; }}
.chip.kind-consumes {{ background: #F1E7F7; color: #7A4FB0; }}

.gap-card {{
    background: white; border: 1px solid #E3E8EF; border-left: 5px solid {AMBER};
    border-radius: 10px; padding: 14px 16px; margin-bottom: 10px;
}}
</style>
"""


def inject() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def page_heading(title: str, badge: str, caption: str) -> None:
    st.markdown(
        f'<div class="atlaz-header"><h1>{title}</h1><span class="badge">{badge}</span></div>',
        unsafe_allow_html=True,
    )
    st.caption(caption)


def stat_card(col, number: object, label: str, tone: str = "") -> None:
    col.markdown(
        f'<div class="stat {tone}"><div class="num">{number}</div><div class="lbl">{label}</div></div>',
        unsafe_allow_html=True,
    )


def chip_html(text: str, kind: str = "") -> str:
    css_class = f"chip kind-{kind}" if kind else "chip"
    return f'<span class="{css_class}">{text}</span>'


def chips(items: list[str], kind: str = "") -> None:
    if not items:
        return
    st.markdown("".join(chip_html(item, kind) for item in items), unsafe_allow_html=True)

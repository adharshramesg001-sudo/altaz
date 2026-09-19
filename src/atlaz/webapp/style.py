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
PURPLE = "#7A4FB0"

_CSS = f"""
<style>
.block-container {{ padding-top: 1.6rem; max-width: 1120px; }}
h1 {{ color: {NAVY}; }}

.atlaz-hero {{
    background: linear-gradient(135deg, {NAVY} 0%, {TEAL} 100%);
    border-radius: 18px; padding: 32px 38px; margin-bottom: 1.6rem; color: white;
    box-shadow: 0 12px 28px -14px rgba(22, 50, 79, 0.55);
}}
.atlaz-hero h1 {{ color: white; font-size: 2.15rem; margin: 0; line-height: 1.2; }}
.atlaz-hero .tagline {{ color: #DCEAF3; font-size: 1.02rem; margin-top: 8px; max-width: 46rem; }}
.atlaz-hero .pill-row {{ margin-top: 16px; }}
.atlaz-hero .pill {{
    display: inline-block; background: rgba(255,255,255,0.14); border: 1px solid rgba(255,255,255,0.4);
    color: white; border-radius: 999px; padding: 4px 14px; margin: 0 8px 8px 0; font-size: 0.82rem;
    font-weight: 500;
}}

.atlaz-header {{ display: flex; align-items: baseline; gap: 10px; margin-bottom: 0.1rem; }}
.atlaz-header .badge {{
    background: {NAVY}; color: white; border-radius: 999px; padding: 2px 14px;
    font-size: 0.8rem; font-weight: 600; letter-spacing: 0.03em;
}}

/* Tinted "bands" behind each pipeline stage's tab panel so the three tabs
   feel like distinct rooms rather than the same white panel relabeled. */
.st-key-band-ingest, .st-key-band-retrieve, .st-key-band-modernize {{
    border-radius: 16px; padding: 1.6rem 1.8rem 1.8rem;
}}
.st-key-band-ingest {{ background: linear-gradient(180deg, rgba(31,122,140,0.07) 0%, rgba(31,122,140,0.015) 100%); }}
.st-key-band-retrieve {{ background: linear-gradient(180deg, rgba(22,50,79,0.06) 0%, rgba(22,50,79,0.012) 100%); }}
.st-key-band-modernize {{ background: linear-gradient(180deg, rgba(122,79,176,0.07) 0%, rgba(122,79,176,0.015) 100%); }}

/* Top-level tabs -- bigger, bolder, with an underline sweep on the active
   tab instead of Streamlit's default thin/quiet tab strip. */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; border-bottom: 2px solid #E3E8EF; }}
.stTabs [data-baseweb="tab"] {{
    height: 46px; padding: 0 18px; font-size: 1.0rem; font-weight: 600; color: #5B6677;
}}
.stTabs [data-baseweb="tab"]:hover {{ color: {NAVY}; background: #EEF3F8; border-radius: 10px 10px 0 0; }}
.stTabs [aria-selected="true"] {{ color: {TEAL} !important; }}
.stTabs [data-baseweb="tab-highlight"] {{ background-color: {TEAL}; height: 3px; }}

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


def hero(title: str, tagline: str, badges: list[str] | None = None) -> None:
    """Gradient banner at the top of the app -- the project's name/identity,
    shown once, above the tabs."""
    badges_html = ""
    if badges:
        pills = "".join(f'<span class="pill">{b}</span>' for b in badges)
        badges_html = f'<div class="pill-row">{pills}</div>'
    st.markdown(
        f'<div class="atlaz-hero"><h1>{title}</h1><div class="tagline">{tagline}</div>{badges_html}</div>',
        unsafe_allow_html=True,
    )


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

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

[id^="section-"] {{ scroll-margin-top: 4.5rem; }}

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

.section-divider {{ margin: 2.4rem 0 1.8rem 0; border: none; border-top: 2px solid #E3E8EF; }}

/* Tinted "bands" behind each pipeline stage so the single scrolling page
   reads as distinct steps rather than one flat wall of white. */
.st-key-band-ingest, .st-key-band-project, .st-key-band-retrieve, .st-key-band-modernize {{
    border-radius: 16px; padding: 1.6rem 1.8rem 1.8rem;
}}
.st-key-band-ingest {{ background: linear-gradient(180deg, rgba(31,122,140,0.07) 0%, rgba(31,122,140,0.015) 100%); }}
.st-key-band-project {{ background: rgba(91, 102, 119, 0.06); }}
.st-key-band-retrieve {{ background: linear-gradient(180deg, rgba(22,50,79,0.06) 0%, rgba(22,50,79,0.012) 100%); }}
.st-key-band-modernize {{ background: linear-gradient(180deg, rgba(122,79,176,0.07) 0%, rgba(122,79,176,0.015) 100%); }}

.atlaz-nav a {{
    display: block; padding: 6px 10px; margin-bottom: 2px; border-radius: 8px; color: {NAVY};
    text-decoration: none; font-size: 0.9rem; font-weight: 500;
}}
.atlaz-nav a:hover {{ background: #EEF3F8; }}

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
    """Gradient banner at the top of the single-page app -- the project's
    name/identity, shown once, above all three sections."""
    badges_html = ""
    if badges:
        pills = "".join(f'<span class="pill">{b}</span>' for b in badges)
        badges_html = f'<div class="pill-row">{pills}</div>'
    st.markdown(
        f'<div class="atlaz-hero"><h1>{title}</h1><div class="tagline">{tagline}</div>{badges_html}</div>',
        unsafe_allow_html=True,
    )


def anchor(section_id: str) -> None:
    """An in-page scroll target -- pair with `sidebar_nav()` so the sidebar
    can jump straight to a section on this single scrolling page."""
    st.markdown(f'<div id="section-{section_id}"></div>', unsafe_allow_html=True)


def sidebar_nav(items: list[tuple[str, str]]) -> None:
    links = "".join(f'<a href="#section-{section_id}">{label}</a>' for label, section_id in items)
    st.markdown(f'<div class="atlaz-nav">{links}</div>', unsafe_allow_html=True)


def section_divider() -> None:
    st.markdown('<hr class="section-divider" />', unsafe_allow_html=True)


def page_heading(title: str, badge: str, caption: str, anchor_id: str | None = None) -> None:
    if anchor_id:
        anchor(anchor_id)
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

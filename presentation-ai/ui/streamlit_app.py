"""Minimal internal tool to upload a .pptx and inspect the JSON output while
developing. NOT the HR-facing product - the actual product is the JSON API
(app/api/routes_presentation.py). Run with: streamlit run ui/streamlit_app.py
"""
from __future__ import annotations

import requests
import streamlit as st

st.set_page_config(page_title="Presentation AI - dev inspector", page_icon="🎯", layout="wide")

# --- Design tokens ---------------------------------------------------------
STATUS_COLORS = {
    "supported": "#22C55E",
    "contradicted": "#EF4444",
    "plausibility_flag": "#F59E0B",
    "project_unsupported": "#38BDF8",
    "unclear": "#94A3B8",
    "not_checkable": "#6B7280",
}
SEVERITY_COLORS = {
    "critical": "#EF4444",
    "high": "#F97316",
    "medium": "#F59E0B",
    "low": "#94A3B8",
}
TRACK_COLORS = {"objective": "#818CF8", "project_specific": "#2DD4BF"}

# --- Global CSS --------------------------------------------------------------
st.markdown(
    '''
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .app-hero {
        padding: 1.75rem 2rem;
        border-radius: 18px;
        background: linear-gradient(135deg, #1E1B4B 0%, #0B0F19 70%);
        border: 1px solid #2A2F45;
        margin-bottom: 1.5rem;
    }
    .app-hero h1 {
        font-size: 1.9rem;
        font-weight: 800;
        margin: 0;
        background: linear-gradient(90deg, #A5B4FC, #67E8F9);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .app-hero p { color: #9CA3AF; margin: .35rem 0 0 0; font-size: .95rem; }

    .card {
        background: #151B2B;
        border: 1px solid #262C40;
        border-radius: 14px;
        padding: 1.1rem 1.3rem;
        margin-bottom: .9rem;
    }
    .card:hover { border-color: #3B4260; }

    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: .72rem;
        font-weight: 700;
        letter-spacing: .02em;
        color: #0B0F19;
        margin-right: 6px;
    }
    .badge-outline {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 999px;
        font-size: .72rem;
        font-weight: 600;
        border: 1px solid #363C55;
        color: #C7CBE0;
        margin-right: 6px;
        background: transparent;
    }

    .claim-text { font-size: .95rem; color: #F1F5F9; margin: .5rem 0; line-height: 1.5; }
    .reason-text { font-size: .85rem; color: #9CA3AF; font-style: italic; margin-top: .3rem; }
    .slide-tag { color: #6B7280; font-size: .78rem; font-weight: 600; }

    .source-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        color: #818CF8;
        font-size: .75rem;
        margin: .25rem .3rem .25rem 0;
        padding: 3px 10px;
        background: #1A1F35;
        border: 1px solid #2E3555;
        border-radius: 999px;
        text-decoration: none;
        transition: border-color .15s;
    }
    .source-pill:hover { border-color: #818CF8; color: #A5B4FC; }

    .sources-block {
        margin-top: .6rem;
        padding-top: .5rem;
        border-top: 1px solid #1E2438;
    }

    .score-ring {
        text-align: center;
        padding: 1.1rem .5rem;
        border-radius: 14px;
        background: #151B2B;
        border: 1px solid #262C40;
    }
    .score-ring .value { font-size: 2.1rem; font-weight: 800; }
    .score-ring .label { color: #9CA3AF; font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; }

    .interview-q {
        border-left: 3px solid #F59E0B;
        padding: .6rem .9rem;
        margin-bottom: .6rem;
        background: #1A1508;
        border-radius: 0 10px 10px 0;
        font-size: .9rem;
        color: #FDE68A;
    }

    div.stButton > button {
        border-radius: 10px;
        font-weight: 700;
        border: none;
        background: linear-gradient(90deg, #6366F1, #22D3EE);
        color: white;
        padding: .55rem 1.4rem;
    }
    div.stButton > button:hover { filter: brightness(1.1); }
    </style>
    ''',
    unsafe_allow_html=True,
)


def badge(text: str, color: str) -> str:
    return f'<span class="badge" style="background:{color};">{text.upper()}</span>'


def score_color(value: int) -> str:
    if value >= 80:
        return "#22C55E"
    if value >= 50:
        return "#F59E0B"
    return "#EF4444"


def _build_evidence_html(evidence_list: list[dict]) -> str:
    """Returns clean source pills HTML, or empty string if no valid URLs."""
    pills = "".join(
        f'<a class="source-pill" href="{e["source_url"]}" target="_blank">'
        f'🔗 Source {i + 1}'
        f'</a>'
        for i, e in enumerate(evidence_list)
        if e.get("source_url")
    )
    if not pills:
        return ""
    return f'<div class="sources-block">{pills}</div>'


def _render_snippet(snippet: str) -> str:
    """Strip stray HTML/angle brackets and truncate for safe display."""
    import re
    clean = re.sub(r"<[^>]+>", "", snippet)   # strip HTML tags
    clean = clean.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return clean[:300].strip()


# --- Header ------------------------------------------------------------------
st.markdown(
    '''
    <div class="app-hero">
        <h1>Presentation AI - Dev Inspector</h1>
        <p>Internal tool only. The real product is the JSON API - this view is for developers to sanity-check pipeline output.</p>
    </div>
    ''',
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("### Settings")
    api_url = st.text_input("API base URL", "http://localhost:8100")
    st.caption("Change this if the Flask server is running elsewhere.")
    st.divider()
    st.caption("Status colors")
    for status, color in STATUS_COLORS.items():
        st.markdown(badge(status, color), unsafe_allow_html=True)

uploaded = st.file_uploader("Upload a .pptx or .pdf presentation", type=["pptx", "pdf"])

if uploaded:
    if "analysis_busy" not in st.session_state:
        st.session_state.analysis_busy = False

    if st.button("Analyze", disabled=st.session_state.analysis_busy):
        st.session_state.analysis_busy = True
        try:
            with st.spinner("Calling /api/v1/presentation/analyze ..."):
                try:
                    resp = requests.post(
                        f"{api_url}/api/v1/presentation/analyze",
                        files={"file": (uploaded.name, uploaded.getvalue())},
                        timeout=1200,
                    )
                except requests.exceptions.RequestException as exc:
                    st.error(f"Connection failed to {api_url}/api/v1/presentation/analyze: {exc}")
                    st.stop()

            if resp.ok:
                st.session_state.last_result = resp.json()
            else:
                st.error(f"{resp.status_code}: {resp.text}")
        finally:
            st.session_state.analysis_busy = False

# --- Results -------------------------------------------------------------------
data = st.session_state.get("last_result")

if data:
    scores = data.get("scores", {})
    summary = data.get("summary", {})
    claims = {c["claim_id"]: c for c in data.get("claims", [])}
    verifications = data.get("verifications", [])
    issues = data.get("issues", [])
    questions = data.get("suggested_interview_questions", [])
    score_evidence = data.get("score_evidence") or {}

    st.markdown(f"#### {data.get('presentation', {}).get('filename', 'Untitled')} · {data.get('presentation', {}).get('slide_count', '?')} slides")
    if data.get("brief"):
        st.markdown(data["brief"])

    # Score row
    cols = st.columns(4)
    for col, (key, label) in zip(cols, [
        ("overall", "Overall"), ("fact_accuracy", "Fact Accuracy"),
        ("evidence_coverage", "Evidence Coverage"), ("claim_reliability", "Reliability"),
    ]):
        value = scores.get(key, 0)
        col.markdown(
            f'''<div class="score-ring">
                <div class="value" style="color:{score_color(value)};">{value}</div>
                <div class="label">{label}</div>
            </div>''',
            unsafe_allow_html=True,
        )

    st.write("")
    completeness = data.get("completeness") or {}
    if completeness.get("status") == "no_extractable_content":
        st.warning("⚠️ No text content could be extracted from this presentation. It may contain only images or scanned slides.")

    if score_evidence:
        with st.expander("Why these scores?"):
            for key, label in [
                ("overall", "Overall"), ("fact_accuracy", "Fact Accuracy"),
                ("evidence_coverage", "Evidence Coverage"), ("reliability", "Reliability"),
            ]:
                if score_evidence.get(key):
                    st.markdown(f"**{label}:** {score_evidence[key]}")

    # Summary badges
    st.markdown(
        " ".join(
            badge(f"{status}: {summary.get(status, 0)}", STATUS_COLORS.get(status, "#6B7280"))
            for status in STATUS_COLORS
        ),
        unsafe_allow_html=True,
    )

    st.write("")
    tab_claims, tab_issues, tab_questions, tab_raw = st.tabs(
        [f"Claims ({len(claims)})", f"Issues ({len(issues)})", f"Interview Questions ({len(questions)})", "Raw JSON"]
    )

    with tab_claims:
        if not verifications:
            st.info("No claims were extracted from this presentation.")
        for v in verifications:
            claim = claims.get(v["claim_id"], {})
            status = v.get("status", "unclear")
            evidence_list = v.get("evidence", [])
            evidence_html = _build_evidence_html(evidence_list)

            with st.container():
                st.markdown(
                    f'''
                    <div class="card">
                        <span class="slide-tag">SLIDE {claim.get('slide_number', '?')}</span>
                        {badge(status, STATUS_COLORS.get(status, '#6B7280'))}
                        <span class="badge-outline">{claim.get('claim_type', '')}</span>
                        <span class="badge-outline">{claim.get('importance', '')}</span>
                        <span class="badge-outline" style="border-color:{TRACK_COLORS.get(claim.get('track',''), '#363C55')};">
                            {claim.get('track', '')}
                        </span>
                        <div class="claim-text">"{claim.get('text', '')}"</div>
                        <div class="reason-text">{v.get('reason', '')}</div>
                        {evidence_html}
                    </div>
                    ''',
                    unsafe_allow_html=True,
                )
                # Snippet expander — rendered via Streamlit (safe, no raw HTML injection)
                valid_evidence = [e for e in evidence_list if e.get("source_url")]
                if valid_evidence:
                    with st.expander("📄 View sources & snippets", expanded=False):
                        for i, e in enumerate(valid_evidence):
                            st.markdown(
                                f"**Source {i + 1}:** [{e['source_url']}]({e['source_url']})",
                                unsafe_allow_html=False,
                            )
                            if e.get("snippet"):
                                st.caption(_render_snippet(e["snippet"]))
                            if i < len(valid_evidence) - 1:
                                st.divider()

    with tab_issues:
        if not issues:
            st.success("No flagged issues.")
        for issue in issues:
            sev = issue.get("severity", "low")
            st.markdown(
                f'''
                <div class="card">
                    {badge(sev, SEVERITY_COLORS.get(sev, '#6B7280'))}
                    <span class="slide-tag">SLIDE {issue.get('slide_number', '?')}</span>
                    <div class="claim-text">"{issue.get('claim_text', '')}"</div>
                    {"<div class='reason-text'>Correction: " + issue['correction'] + "</div>" if issue.get('correction') else ""}
                </div>
                ''',
                unsafe_allow_html=True,
            )

    with tab_questions:
        if not questions:
            st.info("No interview questions were generated.")
        for q in questions:
            st.markdown(
                f'''<div class="interview-q">Slide {q.get('slide_number', '?')}: {q.get('suggested_question', '')}</div>''',
                unsafe_allow_html=True,
            )

    with tab_raw:
        st.json(data)
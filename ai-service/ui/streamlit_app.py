import json
import os

import requests
import streamlit as st
from dotenv import load_dotenv


# =========================
# Configuration
# =========================

load_dotenv()  # يقرأ .env من نفس فولدر المشروع (لو موجود)

BASE_URL = "http://127.0.0.1:5000"
EVALUATE_URL = f"{BASE_URL}/api/v1/cv/evaluate"

# نفس المتغير بالظبط اللي الـ Flask app (config/settings.py) بيقرأه، فمفيش
# احتمال يبقى فيه اختلاف بين المفتاح اللي الـ backend متظبط عليه واللي
# الـ UI بيبعته.
ENV_API_KEY = os.getenv("AI_SERVICE_API_KEY", "")


def get_active_api_key() -> str:
    """المفتاح الفعلي المستخدم: override يدوي من الـ sidebar (لو موجود) وإلا
    القيمة من .env. الـ override بيتخزن في session_state بس - مش بيتكتب
    في أي ملف على الديسك."""
    return st.session_state.get("api_key_override", "").strip() or ENV_API_KEY


# =========================
# Page Configuration
# =========================

st.set_page_config(
    page_title="AMIT Instructor Hub — CV Tools",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# =========================
# Custom CSS — design tokens
# =========================
# لوحة الألوان: navy-charcoal غامق (مش أسود خالص) + دهبي كإكسنت أساسي
# (المرشح اللي "مستحق الاختيار") + تركواز للمطابق وكورال للناقص. الخط:
# Space Grotesk للعناوين (شخصية هندسية واضحة)، Inter للنصوص، JetBrains Mono
# للبيانات الخام.

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

    :root {
        --bg: #0B0F17;
        --bg-glow: radial-gradient(circle at 15% 0%, rgba(232,163,61,0.10), transparent 45%),
                   radial-gradient(circle at 85% 15%, rgba(47,212,165,0.08), transparent 40%);
        --panel: #121826;
        --panel-alt: #17202F;
        --border: #262F42;
        --border-hover: #3A4560;
        --text: #E8ECF3;
        --text-muted: #8993A8;
        --gold: #8B5CF6;
        --gold-soft: rgba(139,92,246,0.16);
        --teal: #2FD4A5;
        --teal-soft: rgba(47,212,165,0.12);
        --coral: #FF6B6B;
        --coral-soft: rgba(255,107,107,0.12);
        --amber: #C084FC;
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }

    .stApp {
        background-color: var(--bg);
        background-image: var(--bg-glow);
        color: var(--text);
    }

    @keyframes fadeSlideUp {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @keyframes scoreReveal {
        from { opacity: 0; transform: scale(0.82); }
        to { opacity: 1; transform: scale(1); }
    }
    @media (prefers-reduced-motion: reduce) {
        * { animation: none !important; transition: none !important; }
    }

    /* ---------- Masthead ---------- */
    .eyebrow {
        text-align: center;
        letter-spacing: 3px;
        text-transform: uppercase;
        font-size: 12px;
        font-weight: 600;
        color: var(--gold);
        margin-top: 18px;
        margin-bottom: 6px;
    }
    .main-title {
        text-align: center;
        font-family: 'Space Grotesk', sans-serif;
        font-size: 44px;
        font-weight: 700;
        letter-spacing: -0.5px;
        margin-bottom: 4px;
        color: var(--text);
    }
    .subtitle {
        text-align: center;
        color: var(--text-muted);
        font-size: 16px;
        margin-bottom: 20px;
    }
    .masthead-divider {
        height: 2px;
        max-width: 220px;
        margin: 0 auto 34px auto;
        background: linear-gradient(90deg, transparent, var(--gold), var(--teal), transparent);
        border-radius: 4px;
    }

    /* ---------- Section titles ---------- */
    .section-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 20px;
        font-weight: 600;
        margin-top: 22px;
        margin-bottom: 14px;
        color: var(--text);
    }

    /* ---------- Cards ---------- */
    .info-card, .experience-card {
        background-color: var(--panel);
        border: 1px solid var(--border);
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 14px;
        animation: fadeSlideUp 0.45s ease both;
        transition: border-color 0.2s ease, transform 0.2s ease, box-shadow 0.2s ease;
    }
    .info-card:hover, .experience-card:hover {
        border-color: var(--border-hover);
        transform: translateY(-2px);
        box-shadow: 0 8px 24px rgba(0,0,0,0.28);
    }
    .experience-card {
        border-left: 3px solid var(--teal);
    }
    .info-label {
        color: var(--text-muted);
        font-size: 12px;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        margin-bottom: 6px;
    }
    .info-value {
        font-size: 16px;
        font-weight: 500;
        color: var(--text);
    }

    /* ---------- Skill pills ---------- */
    .skill, .skill-matched, .skill-missing {
        display: inline-block;
        border-radius: 20px;
        padding: 6px 14px;
        margin: 4px;
        font-size: 13px;
        font-weight: 500;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
        animation: fadeSlideUp 0.4s ease both;
    }
    .skill:hover, .skill-matched:hover, .skill-missing:hover {
        transform: translateY(-2px) scale(1.04);
    }
    .skill {
        background-color: var(--panel-alt);
        border: 1px solid var(--border);
        color: var(--text);
    }
    .skill-matched {
        background-color: var(--teal-soft);
        border: 1px solid var(--teal);
        color: var(--teal);
    }
    .skill-matched:hover { box-shadow: 0 0 0 3px var(--teal-soft); }
    .skill-missing {
        background-color: var(--coral-soft);
        border: 1px solid var(--coral);
        color: var(--coral);
    }
    .skill-missing:hover { box-shadow: 0 0 0 3px var(--coral-soft); }

    /* ---------- Score ring (signature element) ---------- */
    .score-ring-wrap {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 34px 20px;
        background-color: var(--panel);
        border: 1px solid var(--border);
        border-radius: 20px;
        margin-bottom: 22px;
        animation: scoreReveal 0.55s cubic-bezier(0.16,1,0.3,1) both;
    }
    .score-ring {
        width: 172px;
        height: 172px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-bottom: 6px;
    }
    .score-ring-inner {
        width: 138px;
        height: 138px;
        border-radius: 50%;
        background-color: var(--panel);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
    }
    .score-ring-value {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 40px;
        font-weight: 700;
    }
    .score-ring-label {
        font-size: 11px;
        letter-spacing: 1.5px;
        text-transform: uppercase;
        color: var(--text-muted);
        margin-top: 2px;
    }

    /* ---------- Status / connection badge ---------- */
    .status-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        padding: 6px 12px;
        border-radius: 999px;
        border: 1px solid var(--border);
        background-color: var(--panel-alt);
        color: var(--text-muted);
    }
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
    }
    .status-dot.on { background-color: var(--teal); box-shadow: 0 0 8px var(--teal); }
    .status-dot.off { background-color: var(--coral); box-shadow: 0 0 8px var(--coral); }

    .footer-status {
        text-align: center;
        color: var(--text-muted);
        margin-top: 10px;
        font-size: 13px;
    }

    /* ---------- Streamlit widget overrides ---------- */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 1px solid var(--border);
    }
    .stTabs [data-baseweb="tab"] {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        color: var(--text-muted);
        background-color: transparent;
        border-radius: 10px 10px 0 0;
        padding: 10px 18px;
    }
    .stTabs [aria-selected="true"] {
        color: var(--gold) !important;
        border-bottom: 2px solid var(--gold) !important;
    }

    .stButton > button {
        font-family: 'Space Grotesk', sans-serif;
        font-weight: 600;
        border-radius: 12px;
        border: 1px solid var(--gold);
        background: linear-gradient(135deg, var(--gold), var(--amber));
        color: #F5F0FF;
        transition: transform 0.15s ease, box-shadow 0.15s ease;
    }
    .stButton > button:hover {
        transform: translateY(-1px);
        box-shadow: 0 6px 18px var(--gold-soft);
    }

    [data-testid="stFileUploader"], .stTextArea textarea, .stTextInput input {
        background-color: var(--panel) !important;
        border-radius: 12px !important;
        border: 1px solid var(--border) !important;
        color: var(--text) !important;
    }

    pre, code {
        font-family: 'JetBrains Mono', monospace !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# Sidebar — connection / API key
# =========================

with st.sidebar:
    st.markdown("#### الاتصال بالـ AI Service")

    if ENV_API_KEY:
        st.markdown(
            '<div class="status-badge"><span class="status-dot on"></span>'
            "المفتاح اتقرا من ملف .env</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="status-badge"><span class="status-dot off"></span>'
            "مفيش AI_SERVICE_API_KEY في .env</div>",
            unsafe_allow_html=True,
        )

    with st.expander("استخدام مفتاح مختلف مؤقتًا"):
        override = st.text_input(
            "X-API-Key (اختياري)",
            type="password",
            value=st.session_state.get("api_key_override", ""),
            help="بيتخزن في الجلسة الحالية بس، مش بيتكتب في أي ملف. "
            "سيبه فاضي عشان يستخدم القيمة من .env تلقائيًا.",
        )
        st.session_state["api_key_override"] = override


# =========================
# Header
# =========================

st.markdown('<div class="eyebrow">AMIT · Talent Intelligence</div>', unsafe_allow_html=True)
st.markdown('<div class="main-title">Instructor Hub — CV Tools</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">Extract CVs with AI, then rank them against a job description</div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="masthead-divider"></div>', unsafe_allow_html=True)


# =========================
# Helper Functions
# =========================

def safe_value(value, default="Not provided"):
    """Return a readable value for missing or empty fields."""

    if value is None:
        return default

    if isinstance(value, str):
        value = value.strip()

        if not value:
            return default

        return value

    return value


def display_list(items, css_class="skill"):
    """Display list items as tags."""

    if not items:
        st.write("Not provided")
        return

    if isinstance(items, str):
        items = [items]

    html = ""

    for item in items:
        html += f'<span class="{css_class}">{item}</span>'

    st.markdown(html, unsafe_allow_html=True)


def display_value(value):
    """Display a value safely."""

    if isinstance(value, list):
        display_list(value)
    elif isinstance(value, dict):
        st.json(value)
    else:
        st.write(safe_value(value))


def call_api(url, *, files=None, json_payload=None, timeout=300):
    """POST to the Flask API and return the response, or None on a
    connection-level failure (already reported to the user via st.error).
    بيبعت X-API-Key تلقائيًا (من .env أو الـ override في الـ sidebar)."""

    api_key = get_active_api_key()
    headers = {"X-API-Key": api_key} if api_key else {}

    try:
        response = requests.post(
            url,
            files=files,
            json=json_payload,
            headers=headers,
            timeout=timeout,
        )
        return response

    except requests.exceptions.ConnectionError:
        st.error(
            "Could not connect to the Flask API. "
            "Make sure `python app/main.py` is running on port 5000."
        )
        return None

    except requests.exceptions.Timeout:
        st.error("The request timed out.")
        return None

    except requests.exceptions.RequestException as e:
        st.error(f"Request failed: {e}")
        return None


def show_api_error(response):
    """Render the {"success": False, "error": ...} envelope app/main.py
    returns on every non-200 response."""

    try:
        error_data = response.json()
        error_message = error_data.get("error", "Unknown API error.")
        if response.status_code == 401:
            st.error(
                f"API Error: {error_message} — تأكد إن AI_SERVICE_API_KEY متظبط "
                "صح في .env أو في خانة الـ override بالـ sidebar."
            )
        else:
            st.error(f"API Error: {error_message}")
    except ValueError:
        st.error(f"API returned status code {response.status_code}")


def score_ring_html(score: float) -> str:
    """SVG-free circular gauge built with a conic-gradient div — الـ
    signature element بتاع صفحة الـ ranking."""

    score = max(0.0, min(100.0, score))
    color = "#2FD4A5" if score >= 70 else "#F2B84B" if score >= 40 else "#FF6B6B"
    deg = score / 100 * 360

    return f"""
    <div class="score-ring-wrap">
        <div class="score-ring" style="background: conic-gradient({color} {deg}deg, #1E2534 {deg}deg 360deg);">
            <div class="score-ring-inner">
                <div class="score-ring-value" style="color:{color}">{score:.1f}</div>
                <div class="score-ring-label">Match Score</div>
            </div>
        </div>
    </div>
    """


# =========================
# Tabs — Evaluate CV
# =========================

evaluate_tab = st.tabs(["📄 Evaluate CV"])[0]


# ============================================================
# TAB — Evaluate CV  (POST /api/v1/cv/evaluate)
# ============================================================

with evaluate_tab:

    st.markdown(
        '<div class="section-title">Upload your CV and job description</div>',
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader(
        "Drop your CV here",
        type=["pdf", "docx"],
        help="Supported formats: PDF and DOCX",
    )

    if uploaded_file:
        st.success(f"Selected file: {uploaded_file.name}")
        file_size_mb = uploaded_file.size / (1024 * 1024)
        st.caption(f"File size: {file_size_mb:.2f} MB")

    jd_title = st.text_input("Job title", value="Data Analyst")

    col1, col2 = st.columns(2)
    with col1:
        required_skills_text = st.text_area(
            "Required skills (one per line)",
            value="Python\nSQL\nPower BI",
            height=120,
        )
    with col2:
        nice_to_have_text = st.text_area(
            "Nice-to-have skills (one per line)",
            value="Tableau",
            height=120,
        )

    min_experience_years = st.number_input(
        "Minimum experience (years) — optional",
        min_value=0,
        max_value=40,
        value=0,
        step=1,
        help="Leave at 0 to skip this requirement.",
    )

    evaluate_button = st.button(
        "Evaluate CV",
        type="primary",
        use_container_width=True,
    )

    if evaluate_button:

        if uploaded_file is None:
            st.warning("Please upload a PDF or DOCX CV first.")
        else:
            job_description = {
                "title": jd_title,
                "required_skills": [s.strip() for s in required_skills_text.splitlines() if s.strip()],
                "nice_to_have_skills": [s.strip() for s in nice_to_have_text.splitlines() if s.strip()],
            }
            if min_experience_years > 0:
                job_description["min_experience_years"] = int(min_experience_years)

            files = {
                "file": (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type,
                ),
                "job_description": (None, json.dumps(job_description), "application/json"),
            }

            with st.spinner("Extracting CV and scoring it against the job description..."):
                response = call_api(EVALUATE_URL, files=files)

            if response is not None:
                if response.status_code == 200:
                    try:
                        result = response.json()
                        st.session_state["evaluate_result"] = result
                        st.session_state["uploaded_file_name"] = uploaded_file.name
                        st.success("CV evaluation completed successfully.")
                    except ValueError:
                        st.error("The API returned an invalid JSON response.")
                else:
                    show_api_error(response)

    if "evaluate_result" in st.session_state:
        payload = st.session_state["evaluate_result"]
        cv = payload.get("cv", {})
        ranking_result = payload.get("ranking")
        personal = cv.get("personal_info") or {}

        st.markdown("---")
        st.markdown(
            '<div class="section-title">Extracted CV</div>',
            unsafe_allow_html=True,
        )

        info_tab, raw_tab = st.tabs(["Extracted Information", "Raw JSON"])

        with info_tab:
            st.markdown(
                '<div class="section-title">Personal Information</div>',
                unsafe_allow_html=True,
            )

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">Name</div>'
                    f'<div class="info-value">{safe_value(personal.get("name"))}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
            with col2:
                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">Email</div>'
                    f'<div class="info-value">{safe_value(personal.get("email"))}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">Phone</div>'
                    f'<div class="info-value">{safe_value(personal.get("phone"))}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
            with col2:
                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">Location</div>'
                    f'<div class="info-value">{safe_value(personal.get("location"))}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )

            st.markdown('<div class="section-title">Skills (explicit)</div>', unsafe_allow_html=True)
            st.markdown('<div class="info-card">', unsafe_allow_html=True)
            display_list(cv.get("skills"))
            st.markdown("</div>", unsafe_allow_html=True)

            inferred_skills = cv.get("inferred_skills")
            if inferred_skills:
                st.markdown('<div class="section-title">Skills (inferred)</div>', unsafe_allow_html=True)
                st.markdown('<div class="info-card">', unsafe_allow_html=True)
                display_list(inferred_skills)
                st.markdown("</div>", unsafe_allow_html=True)

            experience = cv.get("experience")
            st.markdown('<div class="section-title">Experience</div>', unsafe_allow_html=True)
            if experience:
                for job in experience:
                    if isinstance(job, dict):
                        st.markdown(
                            '<div class="experience-card">'
                            f"<strong>{safe_value(job.get('job_title'))}</strong><br>"
                            f"{safe_value(job.get('company'))}<br>"
                            f"{safe_value(job.get('start_date'))} - {safe_value(job.get('end_date'))}"
                            "</div>",
                            unsafe_allow_html=True,
                        )
            else:
                st.write("Not provided")

        with raw_tab:
            st.json(cv)
            st.download_button(
                label="Download extracted CV JSON",
                data=json.dumps(cv, ensure_ascii=False, indent=2),
                file_name="extracted_cv.json",
                mime="application/json",
                use_container_width=True,
            )

        st.markdown("---")
        st.markdown(
            '<div class="section-title">Ranking Result</div>',
            unsafe_allow_html=True,
        )

        if ranking_result is None:
            st.info("Ranking is disabled for this deployment; extraction completed successfully.")
        else:
            score = ranking_result.get("score", 0)
            st.markdown(score_ring_html(score), unsafe_allow_html=True)
            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<div class="section-title">Matched Skills</div>', unsafe_allow_html=True)
                st.markdown('<div class="info-card">', unsafe_allow_html=True)
                display_list(ranking_result.get("matched_skills"), css_class="skill-matched")
                st.markdown("</div>", unsafe_allow_html=True)
            with col2:
                st.markdown('<div class="section-title">Missing Skills</div>', unsafe_allow_html=True)
                st.markdown('<div class="info-card">', unsafe_allow_html=True)
                display_list(ranking_result.get("missing_skills"), css_class="skill-missing")
                st.markdown("</div>", unsafe_allow_html=True)
            semantic_fit = ranking_result.get("semantic_fit")
            if semantic_fit is not None:
                st.caption(f"Semantic fit (embedding similarity): {semantic_fit:.2f}")
            with st.expander("Score breakdown"):
                st.json(ranking_result.get("breakdown", {}))

            st.download_button(
                label="Download ranking JSON",
                data=json.dumps(ranking_result, ensure_ascii=False, indent=2),
                file_name="ranking_result.json",
                mime="application/json",
                use_container_width=True,
            )


# =========================
# Footer
# =========================

st.markdown("---")

_key_status = "🟢 X-API-Key from .env" if ENV_API_KEY else "🔴 No X-API-Key configured"
st.markdown(
    f'<div class="footer-status">AMIT Instructor Hub · Flask API · Extraction + Ranking · {_key_status}</div>',
    unsafe_allow_html=True,
)
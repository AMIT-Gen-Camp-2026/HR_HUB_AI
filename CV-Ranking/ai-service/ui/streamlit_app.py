import json

import requests
import streamlit as st


# =========================
# Configuration
# =========================

BASE_URL = "http://127.0.0.1:5000"
EXTRACT_URL = f"{BASE_URL}/api/v1/cv/extract"
RANK_URL = f"{BASE_URL}/api/v1/rank"


# =========================
# Page Configuration
# =========================

st.set_page_config(
    page_title="AMIT Instructor Hub — CV Tools",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# =========================
# Custom CSS
# =========================

st.markdown(
    """
    <style>

    .stApp {
        background-color: #0e1117;
    }

    .main-title {
        text-align: center;
        font-size: 42px;
        font-weight: 700;
        margin-top: 20px;
        margin-bottom: 5px;
    }

    .subtitle {
        text-align: center;
        color: #9ca3af;
        font-size: 17px;
        margin-bottom: 35px;
    }

    .section-title {
        font-size: 24px;
        font-weight: 600;
        margin-top: 25px;
        margin-bottom: 15px;
    }

    .info-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 15px;
    }

    .info-label {
        color: #8b949e;
        font-size: 13px;
        margin-bottom: 5px;
    }

    .info-value {
        font-size: 17px;
        font-weight: 500;
    }

    .skill {
        display: inline-block;
        background-color: #21262d;
        border: 1px solid #30363d;
        border-radius: 20px;
        padding: 6px 12px;
        margin: 4px;
        font-size: 14px;
    }

    .skill-matched {
        display: inline-block;
        background-color: #0d2818;
        border: 1px solid #2ea043;
        color: #3fb950;
        border-radius: 20px;
        padding: 6px 12px;
        margin: 4px;
        font-size: 14px;
    }

    .skill-missing {
        display: inline-block;
        background-color: #2d1418;
        border: 1px solid #f85149;
        color: #ff7b72;
        border-radius: 20px;
        padding: 6px 12px;
        margin: 4px;
        font-size: 14px;
    }

    .experience-card {
        background-color: #161b22;
        border-left: 3px solid #58a6ff;
        border-radius: 8px;
        padding: 18px;
        margin-bottom: 12px;
    }

    .score-card {
        background-color: #161b22;
        border: 1px solid #30363d;
        border-radius: 12px;
        padding: 30px;
        text-align: center;
        margin-bottom: 20px;
    }

    .score-value {
        font-size: 56px;
        font-weight: 700;
    }

    .status {
        text-align: center;
        color: #8b949e;
        margin-top: 10px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# =========================
# Header
# =========================

st.markdown(
    '<div class="main-title">AMIT Instructor Hub — CV Tools</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="subtitle">'
    "Extract CVs with AI, then rank them against a job description"
    "</div>",
    unsafe_allow_html=True,
)


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
    connection-level failure (already reported to the user via st.error)."""

    try:
        response = requests.post(
            url,
            files=files,
            json=json_payload,
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
        st.error(f"API Error: {error_message}")
    except ValueError:
        st.error(f"API returned status code {response.status_code}")


# =========================
# Tabs — Extract / Rank
# =========================

extract_tab, rank_tab = st.tabs(["📄 Extract CV", "🎯 Rank Candidate"])


# ============================================================
# TAB 1 — Extract CV  (POST /api/v1/cv/extract)
# ============================================================

with extract_tab:

    st.markdown(
        '<div class="section-title">Upload your CV</div>',
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

    extract_button = st.button(
        "Extract CV",
        type="primary",
        use_container_width=True,
    )

    if extract_button:

        if uploaded_file is None:
            st.warning("Please upload a PDF or DOCX CV first.")

        else:
            files = {
                "file": (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type,
                )
            }

            with st.spinner("Extracting CV information using the AI model..."):
                response = call_api(EXTRACT_URL, files=files)

            if response is not None:

                if response.status_code == 200:
                    try:
                        result = response.json()
                        # الـ candidate اللي هتستخدمه Tab الـ Ranking - نفس
                        # الـ CVSchema بالظبط (result["cv"]), من غير أي تعديل.
                        st.session_state["cv_result"] = result
                        st.session_state["uploaded_file_name"] = uploaded_file.name
                        st.success("CV extraction completed successfully.")
                    except ValueError:
                        st.error("The API returned an invalid JSON response.")
                else:
                    show_api_error(response)

    # ---------------------------------
    # Display Result
    # ---------------------------------

    if "cv_result" in st.session_state:

        cv = st.session_state["cv_result"].get("cv", {})
        personal = cv.get("personal_info") or {}

        st.markdown("---")
        st.markdown(
            '<div class="section-title">Extracted CV</div>',
            unsafe_allow_html=True,
        )

        info_tab, raw_tab = st.tabs(["Extracted Information", "Raw JSON"])

        with info_tab:

            # --- Personal Information ---
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

            col1, col2 = st.columns(2)
            with col1:
                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">LinkedIn</div>'
                    f'<div class="info-value">{safe_value(personal.get("linkedin"))}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
            with col2:
                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">GitHub</div>'
                    f'<div class="info-value">{safe_value(personal.get("github"))}</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )

            # --- Skills (explicit + inferred are separate fields in CVSchema) ---
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

            # --- Experience ---
            experience = cv.get("experience")
            st.markdown('<div class="section-title">Experience</div>', unsafe_allow_html=True)

            if experience:
                for job in experience:
                    if isinstance(job, dict):
                        title = safe_value(job.get("job_title"))
                        company = safe_value(job.get("company"))
                        start_date = safe_value(job.get("start_date"))
                        end_date = safe_value(job.get("end_date"))

                        st.markdown(
                            '<div class="experience-card">'
                            f"<strong>{title}</strong><br>"
                            f"{company}<br>"
                            f"{start_date} - {end_date}"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'<div class="experience-card">{job}</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.write("Not provided")

            # --- Education ---
            education = cv.get("education")
            st.markdown('<div class="section-title">Education</div>', unsafe_allow_html=True)

            if education:
                for item in education:
                    if isinstance(item, dict):
                        degree = safe_value(item.get("degree"))
                        institution = safe_value(item.get("institution"))
                        year = safe_value(item.get("graduation_year"))

                        st.markdown(
                            '<div class="experience-card">'
                            f"<strong>{degree}</strong><br>"
                            f"{institution}<br>"
                            f"{year}"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f'<div class="experience-card">{item}</div>',
                            unsafe_allow_html=True,
                        )
            else:
                st.write("Not provided")

            # --- Projects ---
            projects = cv.get("projects")
            if projects:
                st.markdown('<div class="section-title">Projects</div>', unsafe_allow_html=True)

                for project in projects:
                    if isinstance(project, dict):
                        name = safe_value(project.get("name"))
                        description = safe_value(project.get("description"))
                        technologies = project.get("technologies_mentioned")

                        st.markdown(
                            '<div class="experience-card">'
                            f"<strong>{name}</strong><br><br>"
                            f"{description}"
                            "</div>",
                            unsafe_allow_html=True,
                        )

                        if technologies:
                            st.write("Technologies")
                            display_list(technologies)
                    else:
                        st.markdown(
                            f'<div class="experience-card">{project}</div>',
                            unsafe_allow_html=True,
                        )

            # --- Certifications / Languages ---
            col1, col2 = st.columns(2)

            with col1:
                certifications = cv.get("certifications")
                if certifications:
                    st.markdown('<div class="section-title">Certifications</div>', unsafe_allow_html=True)
                    st.markdown('<div class="info-card">', unsafe_allow_html=True)
                    display_list(certifications)
                    st.markdown("</div>", unsafe_allow_html=True)

            with col2:
                languages = cv.get("languages")
                if languages:
                    st.markdown('<div class="section-title">Languages</div>', unsafe_allow_html=True)
                    st.markdown('<div class="info-card">', unsafe_allow_html=True)
                    display_list(languages)
                    st.markdown("</div>", unsafe_allow_html=True)

        with raw_tab:
            st.markdown('<div class="section-title">Raw Model Output</div>', unsafe_allow_html=True)
            st.json(cv)
            st.download_button(
                label="Download JSON",
                data=json.dumps(cv, ensure_ascii=False, indent=2),
                file_name="extracted_cv.json",
                mime="application/json",
                use_container_width=True,
            )


# ============================================================
# TAB 2 — Rank Candidate  (POST /api/v1/rank)
# ============================================================

with rank_tab:

    st.markdown(
        '<div class="section-title">Candidate</div>',
        unsafe_allow_html=True,
    )

    has_extracted_cv = "cv_result" in st.session_state

    if has_extracted_cv:
        source_label = f'CV extracted in the other tab ("{st.session_state.get("uploaded_file_name", "uploaded file")}")'
        candidate_source = st.radio(
            "Which candidate do you want to rank?",
            options=["Use the extracted CV", "Paste a CVSchema JSON manually"],
            horizontal=True,
        )
    else:
        st.info(
            "No CV extracted yet in this session. Extract one in the "
            '"Extract CV" tab first, or paste a candidate JSON below.'
        )
        candidate_source = "Paste a CVSchema JSON manually"

    candidate_payload = None

    if candidate_source == "Use the extracted CV":
        candidate_payload = st.session_state["cv_result"]["cv"]
        st.caption(source_label)
        with st.expander("Preview candidate JSON"):
            st.json(candidate_payload)

    else:
        default_candidate = json.dumps(
            {"skills": ["Python", "SQL"], "inferred_skills": ["Pandas"]},
            indent=2,
        )
        candidate_json_text = st.text_area(
            "Candidate JSON (matches CVSchema — at minimum needs `skills`)",
            value=default_candidate,
            height=160,
        )
        try:
            candidate_payload = json.loads(candidate_json_text)
        except json.JSONDecodeError as e:
            st.error(f"Invalid JSON: {e}")

    st.markdown(
        '<div class="section-title">Job Description</div>',
        unsafe_allow_html=True,
    )

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

    rank_button = st.button("Rank Candidate", type="primary", use_container_width=True)

    if rank_button:

        if candidate_payload is None:
            st.warning("Fix the candidate JSON above first.")

        else:
            job_description = {
                "title": jd_title,
                "required_skills": [s.strip() for s in required_skills_text.splitlines() if s.strip()],
                "nice_to_have_skills": [s.strip() for s in nice_to_have_text.splitlines() if s.strip()],
            }
            if min_experience_years > 0:
                job_description["min_experience_years"] = int(min_experience_years)

            payload = {"candidate": candidate_payload, "job_description": job_description}

            with st.spinner("Scoring candidate against the job description..."):
                response = call_api(RANK_URL, json_payload=payload)

            if response is not None:
                if response.status_code == 200:
                    body = response.json()
                    if body.get("success"):
                        st.session_state["rank_result"] = body["result"]
                    else:
                        st.warning(body.get("error", "Ranking is switched off."))
                        st.session_state.pop("rank_result", None)
                else:
                    show_api_error(response)

    # ---------------------------------
    # Display Result
    # ---------------------------------

    if "rank_result" in st.session_state:

        result = st.session_state["rank_result"]

        st.markdown("---")

        score = result.get("score", 0)
        color = "#3fb950" if score >= 70 else "#d29922" if score >= 40 else "#f85149"

        st.markdown(
            '<div class="score-card">'
            '<div class="info-label">Match Score</div>'
            f'<div class="score-value" style="color:{color}">{score:.1f}</div>'
            "</div>",
            unsafe_allow_html=True,
        )

        col1, col2 = st.columns(2)

        with col1:
            st.markdown('<div class="section-title">Matched Skills</div>', unsafe_allow_html=True)
            st.markdown('<div class="info-card">', unsafe_allow_html=True)
            display_list(result.get("matched_skills"), css_class="skill-matched")
            st.markdown("</div>", unsafe_allow_html=True)

        with col2:
            st.markdown('<div class="section-title">Missing Skills</div>', unsafe_allow_html=True)
            st.markdown('<div class="info-card">', unsafe_allow_html=True)
            display_list(result.get("missing_skills"), css_class="skill-missing")
            st.markdown("</div>", unsafe_allow_html=True)

        semantic_fit = result.get("semantic_fit")
        if semantic_fit is not None:
            st.caption(f"Semantic fit (embedding similarity): {semantic_fit:.2f}")

        with st.expander("Score breakdown"):
            st.json(result.get("breakdown", {}))


# =========================
# Footer
# =========================

st.markdown("---")

st.markdown(
    '<div class="status">'
    "AMIT Instructor Hub · Flask API · Extraction + Ranking"
    "</div>",
    unsafe_allow_html=True,
)
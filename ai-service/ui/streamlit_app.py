"""Streamlit demo for the Flask CV extraction, ranking, and video transcription API."""

import html
import json
import os
from collections.abc import Mapping
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()

API_BASE_URL = os.getenv(
    "API_BASE_URL",
    "http://127.0.0.1:5000",
).rstrip("/")

EXTRACT_URL = f"{API_BASE_URL}/api/v1/cv/extract"
RANK_URL = f"{API_BASE_URL}/api/v1/rank"
VIDEO_TRANSCRIBE_URL = f"{API_BASE_URL}/api/v1/video/transcribe"

# Keep the existing timeout for CV extraction and ranking.
REQUEST_TIMEOUT_SECONDS = 120

# Video transcription can take longer because Whisper may need to:
# 1. Load the ASR model
# 2. Decode the video/audio
# 3. Run inference
VIDEO_REQUEST_TIMEOUT_SECONDS = 600


# ---------------------------------------------------------------------------
# Streamlit page setup
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AI CV Screening Demo",
    page_icon="📄",
    layout="wide",
)


for key in (
    "extracted_cv",
    "uploaded_file_name",
    "ranking_result",
    "video_transcription",
):
    st.session_state.setdefault(key, None)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
    .stApp {
        background: #0b1220;
    }

    .block-container {
        max-width: 1180px;
        padding-top: 2.6rem;
    }

    .hero h1 {
        margin: 0;
        color: #f8fafc;
        font-size: 2.45rem;
    }

    .hero p,
    .muted {
        color: #94a3b8;
    }

    .eyebrow {
        color: #60a5fa;
        font-size: .78rem;
        font-weight: 700;
        letter-spacing: .1em;
        text-transform: uppercase;
    }

    .section-heading {
        color: #e2e8f0;
        font-size: 1.3rem;
        font-weight: 650;
        margin: 1.1rem 0 .65rem;
    }

    .card {
        background: #111c30;
        border: 1px solid #263650;
        border-radius: 12px;
        padding: 1rem 1.15rem;
        min-height: 88px;
    }

    .card-label {
        color: #94a3b8;
        font-size: .78rem;
        margin-bottom: .3rem;
    }

    .card-value {
        color: #f8fafc;
        overflow-wrap: anywhere;
    }

    .tag,
    .tag-match,
    .tag-missing {
        display: inline-block;
        border-radius: 999px;
        padding: .3rem .65rem;
        margin: .14rem;
        font-size: .86rem;
    }

    .tag {
        background: #1e293b;
        border: 1px solid #334155;
        color: #dbeafe;
    }

    .tag-match {
        background: #123225;
        border: 1px solid #21824d;
        color: #86efac;
    }

    .tag-missing {
        background: #3b1720;
        border: 1px solid #b94155;
        color: #fecdd3;
    }

    .timeline-card {
        background: #111c30;
        border-left: 3px solid #60a5fa;
        border-radius: 8px;
        padding: .9rem 1rem;
        margin-bottom: .65rem;
    }

    .score-card {
        background: linear-gradient(135deg, #111c30, #17294a);
        border: 1px solid #36598d;
        border-radius: 16px;
        padding: 1.7rem;
        text-align: center;
    }

    .score-label {
        color: #bfdbfe;
        font-size: .9rem;
        text-transform: uppercase;
        letter-spacing: .09em;
    }

    .score-value {
        font-size: 4rem;
        font-weight: 750;
        line-height: 1.05;
    }

    .transcript-card {
        background: #111c30;
        border: 1px solid #263650;
        border-radius: 12px;
        padding: 1rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


st.markdown(
    """
    <div class="hero">
        <div class="eyebrow">Flask API-powered demo</div>
        <h1>AI CV Screening</h1>
        <p>
            Extract structured candidate profiles, assess fit against a role,
            and transcribe candidate videos.
        </p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def safe_text(value: Any, default: str = "Not provided") -> str:
    if value is None:
        return default

    if isinstance(value, str):
        return (
            html.escape(value.strip())
            if value.strip()
            else default
        )

    return html.escape(str(value))


def as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return (
        value
        if isinstance(value, list)
        else ([value] if value not in (None, "") else [])
    )


def show_tags(items: Any, css_class: str = "tag") -> None:
    values = as_list(items)

    if not values:
        st.caption("Not provided")
        return

    st.markdown(
        "".join(
            f'<span class="{css_class}">{safe_text(item)}</span>'
            for item in values
        ),
        unsafe_allow_html=True,
    )


def show_card(label: str, value: Any) -> None:
    st.markdown(
        f"""
        <div class="card">
            <div class="card-label">{html.escape(label)}</div>
            <div class="card-value">{safe_text(value)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def format_error(error: Any) -> str:
    if isinstance(error, list):
        messages = []

        for item in error:
            if isinstance(item, Mapping):
                location = ".".join(
                    str(part)
                    for part in item.get("loc", [])
                    if part != "body"
                )

                message = str(
                    item.get("msg", "Invalid value")
                )

                messages.append(
                    f"{location}: {message}"
                    if location
                    else message
                )
            else:
                messages.append(str(item))

        return (
            "\n".join(f"• {message}" for message in messages)
            or "Invalid request."
        )

    return (
        json.dumps(
            error,
            ensure_ascii=False,
            indent=2,
        )
        if isinstance(error, Mapping)
        else str(error or "Unknown API error.")
    )


def show_api_error(response: requests.Response) -> None:
    detail = None

    try:
        body = response.json()

        error = (
            body.get("error", "The API returned an error.")
            if isinstance(body, Mapping)
            else body
        )

        detail = (
            body.get("detail")
            if isinstance(body, Mapping)
            else None
        )

    except ValueError:
        error = "The API returned a non-JSON error response."

    message = format_error(error)

    if response.status_code == 400:
        st.error(
            f"The request could not be accepted.\n\n{message}"
        )

    elif response.status_code == 422:
        st.error(
            f"The submitted data did not match the API schema.\n\n{message}"
        )

    elif response.status_code == 429:
        st.warning(
            "This request was rate-limited by the API. "
            "Please wait and try again."
        )

    elif response.status_code == 413:
        st.error(
            "The uploaded file is larger than the "
            "server-configured size limit."
        )

    elif response.status_code == 415:
        st.error(
            f"This video format is not supported.\n\n{message}"
        )

    elif response.status_code == 503:
        st.error(
            f"The transcription service is currently unavailable. "
            f"{message}"
        )

        if isinstance(detail, str) and detail:
            st.caption(
                f"Development detail: {detail}"
            )

    elif response.status_code >= 500:
        st.error(
            "The backend could not complete the request. "
            "Please try again shortly."
        )

    else:
        st.error(
            f"API error ({response.status_code}): {message}"
        )


def post_api(
    url: str,
    *,
    files: Any = None,
    payload: Any = None,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> requests.Response | None:
    """
    Send a request to the Flask backend.

    The default timeout remains 120 seconds for CV extraction
    and ranking. Video transcription explicitly uses the longer
    VIDEO_REQUEST_TIMEOUT_SECONDS value.
    """

    try:
        return requests.post(
            url,
            files=files,
            json=payload,
            timeout=timeout,
        )

    except requests.exceptions.ConnectionError:
        st.error(
            "Could not connect to the Flask API. "
            "Start it with `python -m app.main` and confirm "
            "API_BASE_URL is correct."
        )

    except requests.exceptions.Timeout:
        st.error(
            "The API request timed out. "
            "The server may still be processing the upload; "
            "try again shortly."
        )

    except requests.exceptions.RequestException:
        st.error(
            "The request to the Flask API failed. "
            "Please check that the backend is running."
        )

    return None


def success_json(
    response: requests.Response,
) -> Mapping[str, Any] | None:
    try:
        body = response.json()

    except ValueError:
        st.error(
            "The API returned malformed JSON. "
            "Please retry the request."
        )
        return None

    if not isinstance(body, Mapping):
        st.error(
            "The API returned an unexpected response format."
        )
        return None

    return body


# ---------------------------------------------------------------------------
# CV display
# ---------------------------------------------------------------------------

def display_cv(cv: Mapping[str, Any]) -> None:
    st.markdown(
        '<div class="section-heading">Extracted candidate profile</div>',
        unsafe_allow_html=True,
    )

    profile_tab, raw_tab = st.tabs(
        ["Profile", "Raw JSON"]
    )

    with profile_tab:

        st.markdown(
            '<div class="section-heading">Personal information</div>',
            unsafe_allow_html=True,
        )

        personal = as_mapping(
            cv.get("personal_info")
        )

        fields = [
            ("Name", personal.get("name")),
            ("Email", personal.get("email")),
            ("Phone", personal.get("phone")),
            ("Location", personal.get("location")),
            ("LinkedIn", personal.get("linkedin")),
            ("GitHub", personal.get("github")),
        ]

        for first, second in zip(
            fields[::2],
            fields[1::2],
        ):
            left, right = st.columns(2)

            with left:
                show_card(*first)

            with right:
                show_card(*second)

        st.markdown(
            '<div class="section-heading">Skills</div>',
            unsafe_allow_html=True,
        )

        left, right = st.columns(2)

        with left:
            st.caption("EXPLICIT SKILLS")
            show_tags(cv.get("skills"))

        with right:
            st.caption("INFERRED SKILLS")
            show_tags(cv.get("inferred_skills"))

        for heading, key, fields_to_show in [
            (
                "Experience",
                "experience",
                (
                    "job_title",
                    "company",
                    "start_date",
                    "end_date",
                ),
            ),
            (
                "Education",
                "education",
                (
                    "degree",
                    "institution",
                    "graduation_year",
                ),
            ),
        ]:

            st.markdown(
                f'<div class="section-heading">{heading}</div>',
                unsafe_allow_html=True,
            )

            entries = as_list(
                cv.get(key)
            )

            if not entries:
                st.caption("Not provided")

            for item in entries:
                entry = as_mapping(item)

                lines = [
                    safe_text(entry.get(field))
                    for field in fields_to_show
                ]

                st.markdown(
                    f"""
                    <div class="timeline-card">
                        <strong>{lines[0]}</strong><br>
                        {"<br>".join(lines[1:])}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        st.markdown(
            '<div class="section-heading">Projects</div>',
            unsafe_allow_html=True,
        )

        projects = as_list(
            cv.get("projects")
        )

        if not projects:
            st.caption("Not provided")

        for item in projects:
            project = as_mapping(item)

            st.markdown(
                f"""
                <div class="timeline-card">
                    <strong>
                        {safe_text(project.get("name"))}
                    </strong>
                    <br>
                    {safe_text(project.get("description"))}
                </div>
                """,
                unsafe_allow_html=True,
            )

            show_tags(
                project.get("technologies_mentioned")
            )

        left, right = st.columns(2)

        with left:
            st.markdown(
                '<div class="section-heading">Certifications</div>',
                unsafe_allow_html=True,
            )
            show_tags(
                cv.get("certifications")
            )

        with right:
            st.markdown(
                '<div class="section-heading">Languages</div>',
                unsafe_allow_html=True,
            )
            show_tags(
                cv.get("languages")
            )

    with raw_tab:
        st.json(cv)

        st.download_button(
            "Download JSON",
            json.dumps(
                cv,
                ensure_ascii=False,
                indent=2,
            ),
            "extracted_cv.json",
            "application/json",
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# Main tabs
# ---------------------------------------------------------------------------

extract_tab, rank_tab, video_tab = st.tabs(
    [
        "📄 Extract CV",
        "🎯 Rank candidate",
        "🎥 Video Demo",
    ]
)


# ===========================================================================
# TAB 1 — Extract CV
# ===========================================================================

with extract_tab:

    st.markdown(
        '<div class="section-heading">Upload a candidate CV</div>',
        unsafe_allow_html=True,
    )

    uploaded_file = st.file_uploader(
        "PDF or DOCX file",
        type=["pdf", "docx"],
        help="Maximum size is enforced by the API.",
    )

    if uploaded_file is not None:
        st.success(
            f"Ready to extract: {uploaded_file.name}"
        )

        st.caption(
            f"File size: "
            f"{uploaded_file.size / (1024 * 1024):.2f} MB"
        )

    if st.button(
        "Extract CV",
        type="primary",
        use_container_width=True,
    ):

        if uploaded_file is None:

            st.warning(
                "Choose a PDF or DOCX CV before extracting."
            )

        else:

            with st.spinner(
                "Extracting structured CV information…"
            ):

                # IMPORTANT:
                # CV extraction must call EXTRACT_URL.
                response = post_api(
                    EXTRACT_URL,
                    files={
                        "file": (
                            uploaded_file.name,
                            uploaded_file.getvalue(),
                            uploaded_file.type,
                        )
                    },
                )

            if response is not None:

                if response.status_code != 200:

                    show_api_error(response)

                else:

                    body = success_json(response)

                    cv = (
                        body.get("cv")
                        if body
                        and body.get("success")
                        else None
                    )

                    if isinstance(cv, Mapping):

                        st.session_state.extracted_cv = dict(cv)

                        st.session_state.uploaded_file_name = (
                            uploaded_file.name
                        )

                        st.success(
                            "CV extraction completed. "
                            "The candidate is ready in "
                            "the Ranking tab."
                        )

                    elif body:

                        st.error(
                            format_error(
                                body.get(
                                    "error",
                                    "The API response did not "
                                    "include a CV.",
                                )
                            )
                        )

    if isinstance(
        st.session_state.extracted_cv,
        Mapping,
    ):
        display_cv(
            st.session_state.extracted_cv
        )


# ===========================================================================
# TAB 2 — Rank Candidate
# ===========================================================================

with rank_tab:

    st.markdown(
        '<div class="section-heading">Candidate source</div>',
        unsafe_allow_html=True,
    )

    has_extracted_cv = isinstance(
        st.session_state.extracted_cv,
        Mapping,
    )

    source = st.radio(
        "Choose a candidate",
        (
            [
                "Use extracted CV",
                "Paste CVSchema JSON",
            ]
            if has_extracted_cv
            else ["Paste CVSchema JSON"]
        ),
        horizontal=True,
    )

    candidate: Mapping[str, Any] | None = None

    if source == "Use extracted CV":

        candidate = st.session_state.extracted_cv

        st.caption(
            "Using the extracted CV from: "
            f"{st.session_state.uploaded_file_name or 'uploaded file'}"
        )

        with st.expander(
            "Preview candidate JSON"
        ):
            st.json(candidate)

    else:

        manual_candidate = st.text_area(
            "Candidate JSON (CVSchema)",
            value=json.dumps(
                {
                    "skills": [
                        "Python",
                        "SQL",
                    ],
                    "inferred_skills": [
                        "Pandas"
                    ],
                },
                indent=2,
            ),
            height=180,
            help=(
                "Use the CVSchema structure returned "
                "by extraction. Unknown fields are "
                "rejected by the API."
            ),
        )

        try:

            parsed = json.loads(
                manual_candidate
            )

            candidate = (
                parsed
                if isinstance(parsed, Mapping)
                else None
            )

            if candidate is None:
                st.error(
                    "Candidate JSON must be an object."
                )

        except json.JSONDecodeError as error:

            st.error(
                f"Malformed candidate JSON: "
                f"{error.msg} "
                f"(line {error.lineno}, "
                f"column {error.colno})."
            )

    st.markdown(
        '<div class="section-heading">Job description</div>',
        unsafe_allow_html=True,
    )

    title = st.text_input(
        "Job title",
        value="Data Analyst",
    )

    required_column, preferred_column = st.columns(2)

    with required_column:

        required_text = st.text_area(
            "Required skills (one per line)",
            value="Python\nSQL\nPower BI",
            height=130,
        )

    with preferred_column:

        preferred_text = st.text_area(
            "Nice-to-have skills (one per line)",
            value="Tableau",
            height=130,
        )

    min_experience = st.number_input(
        "Minimum experience (years, optional)",
        min_value=0,
        max_value=40,
        value=0,
        step=1,
        help=(
            "The backend accepts this field; "
            "it is retained in the request "
            "for compatibility."
        ),
    )

    if st.button(
        "Rank candidate",
        type="primary",
        use_container_width=True,
    ):

        required = [
            skill.strip()
            for skill in required_text.splitlines()
            if skill.strip()
        ]

        preferred = [
            skill.strip()
            for skill in preferred_text.splitlines()
            if skill.strip()
        ]

        if candidate is None:

            st.warning(
                "Provide valid candidate JSON before ranking."
            )

        elif not title.strip():

            st.warning(
                "Enter a job title before ranking."
            )

        elif not required:

            st.warning(
                "Enter at least one required skill before ranking."
            )

        else:

            job = {
                "title": title.strip(),
                "required_skills": required,
                "nice_to_have_skills": preferred,
            }

            if min_experience:
                job["min_experience_years"] = int(
                    min_experience
                )

            with st.spinner(
                "Comparing candidate skills with the role…"
            ):

                response = post_api(
                    RANK_URL,
                    payload={
                        "candidate": candidate,
                        "job_description": job,
                    },
                )

            if response is not None:

                if response.status_code != 200:

                    show_api_error(response)

                else:

                    body = success_json(response)

                    result = (
                        body.get("result")
                        if body
                        and body.get("success")
                        else None
                    )

                    if isinstance(
                        result,
                        Mapping,
                    ):

                        st.session_state.ranking_result = (
                            dict(result)
                        )

                        st.success(
                            "Candidate ranking completed."
                        )

                    elif body:

                        st.info(
                            format_error(
                                body.get(
                                    "error",
                                    "Ranking is not available.",
                                )
                            )
                        )

    result = st.session_state.ranking_result

    if isinstance(result, Mapping):

        st.markdown(
            '<div class="section-heading">Ranking result</div>',
            unsafe_allow_html=True,
        )

        try:
            score = float(
                result.get("score", 0)
            )
        except (TypeError, ValueError):
            score = 0.0

        color = (
            "#86efac"
            if score >= 70
            else "#fcd34d"
            if score >= 40
            else "#fda4af"
        )

        st.markdown(
            f"""
            <div class="score-card">
                <div class="score-label">
                    Match score
                </div>
                <div
                    class="score-value"
                    style="color:{color}"
                >
                    {score:.1f}%
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        matched, missing = st.columns(2)

        with matched:

            st.markdown(
                '<div class="section-heading">Matched skills</div>',
                unsafe_allow_html=True,
            )

            show_tags(
                result.get("matched_skills"),
                "tag-match",
            )

        with missing:

            st.markdown(
                '<div class="section-heading">Missing skills</div>',
                unsafe_allow_html=True,
            )

            show_tags(
                result.get("missing_skills"),
                "tag-missing",
            )

        if result.get("semantic_fit") is not None:

            st.info(
                f"Semantic fit: "
                f"{result['semantic_fit']}"
            )

        with st.expander(
            "Score breakdown"
        ):
            st.json(
                result.get(
                    "breakdown",
                    {},
                )
            )


# ===========================================================================
# TAB 3 — Video Transcription
# ===========================================================================

with video_tab:

    st.markdown(
        '<div class="section-heading">Video Demo</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <p class="muted">
            Upload a video and generate an Arabic, English,
            or mixed-speech transcript using multilingual
            AI speech recognition.
        </p>
        """,
        unsafe_allow_html=True,
    )

    uploaded_video = st.file_uploader(
        "Upload video",
        type=[
            "mp4",
            "mov",
            "mkv",
            "webm",
        ],
        help=(
            "Supported formats: MP4, MOV, MKV, and WebM. "
            "The server enforces the maximum upload size."
        ),
        key="video_uploader",
    )

    if uploaded_video is not None:

        st.success(
            f"Selected video: "
            f"{uploaded_video.name}"
        )

        st.caption(
            f"File size: "
            f"{uploaded_video.size / (1024 * 1024):.2f} MB "
            "· Arabic + English + mixed speech supported"
        )

    if st.button(
        "Transcribe Video",
        type="primary",
        use_container_width=True,
        key="transcribe_video",
    ):

        if uploaded_video is None:

            st.warning(
                "Choose a supported video file "
                "before starting transcription."
            )

        elif uploaded_video.size == 0:

            st.warning(
                "The uploaded video is empty. "
                "Choose another file."
            )

        else:

            with st.spinner(
                "Extracting audio, transcribing "
                "Arabic/English speech, and "
                "preparing the transcript…"
            ):

                # IMPORTANT:
                # Video transcription uses the dedicated
                # longer timeout.
                response = post_api(
                    VIDEO_TRANSCRIBE_URL,
                    files={
                        "file": (
                            uploaded_video.name,
                            uploaded_video.getvalue(),
                            uploaded_video.type,
                        )
                    },
                    timeout=VIDEO_REQUEST_TIMEOUT_SECONDS,
                )

            if response is not None:

                if response.status_code != 200:

                    show_api_error(response)

                else:

                    body = success_json(response)

                    if (
                        body
                        and body.get("success")
                        and isinstance(
                            body.get("text"),
                            str,
                        )
                    ):

                        st.session_state.video_transcription = (
                            dict(body)
                        )

                        st.success(
                            "Video transcription completed."
                        )

                    elif body:

                        st.error(
                            format_error(
                                body.get(
                                    "error",
                                    "The API response did not "
                                    "include a transcript.",
                                )
                            )
                        )

    transcription = (
        st.session_state.video_transcription
    )

    if isinstance(
        transcription,
        Mapping,
    ):

        st.markdown(
            '<div class="section-heading">Transcription result</div>',
            unsafe_allow_html=True,
        )

        language_code = str(
            transcription.get(
                "language",
                "unknown",
            )
        )

        language_label = {
            "ar": "Arabic",
            "en": "English",
        }.get(
            language_code.lower(),
            language_code,
        )

        probability = transcription.get(
            "language_probability"
        )

        language_detail = (
            f"Detected language: "
            f"{language_label}"
        )

        if isinstance(
            probability,
            (float, int),
        ):

            language_detail += (
                f" ({probability:.0%} confidence)"
            )

        st.info(
            language_detail
            + ". Mixed Arabic + English speech "
            "is preserved without translation."
        )

        transcript_text = str(
            transcription.get(
                "text",
                "",
            )
        )

        st.text_area(
            "Transcript",
            value=transcript_text,
            height=260,
            disabled=True,
            key="transcript_output",
        )

        download_left, download_right = st.columns(2)

        with download_left:

            st.download_button(
                "Download TXT",
                transcript_text,
                "video_transcript.txt",
                "text/plain",
                use_container_width=True,
            )

        with download_right:

            st.download_button(
                "Download JSON",
                json.dumps(
                    transcription,
                    ensure_ascii=False,
                    indent=2,
                ),
                "video_transcript.json",
                "application/json",
                use_container_width=True,
            )

        segments = as_list(
            transcription.get("segments")
        )

        if segments:

            with st.expander(
                "Transcript segments"
            ):

                for segment in segments:

                    entry = as_mapping(
                        segment
                    )

                    start = entry.get(
                        "start",
                        0,
                    )

                    end = entry.get(
                        "end",
                        0,
                    )

                    st.markdown(
                        f"""
                        **{float(start):06.2f}s –
                        {float(end):06.2f}s**
                        {safe_text(entry.get("text"))}
                        """,
                        unsafe_allow_html=True,
                    )


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown(
    """
    <p class='muted'
       style='text-align:center; margin-top:2rem;'>
        AI CV Screening · Flask API ·
        Extraction + Ranking + Transcription
    </p>
    """,
    unsafe_allow_html=True,
)
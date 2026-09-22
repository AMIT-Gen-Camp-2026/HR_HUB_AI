import os
import re
import logging
from typing import List, Dict, Any, Optional
from groq import Groq

logger = logging.getLogger("groq_client")

# Load environment variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "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")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

_groq_client = None


def get_groq_client():
    global _groq_client
    if _groq_client is None:
        try:
            api_key = os.getenv("GROQ_API_KEY", GROQ_API_KEY)
            if api_key and api_key.startswith("gsk_"):
                _groq_client = Groq(api_key=api_key)
            else:
                _groq_client = None
        except Exception as e:
            logger.error(f"Failed to initialize Groq client: {e}")
            _groq_client = None
    return _groq_client


# ---------------------------------------------------------------------------
# Fallback / Deterministic High-Quality Data Formatter
# ---------------------------------------------------------------------------
def format_data_response_deterministic(
    question: str,
    lecturers: List[Dict[str, Any]],
    filters: Dict[str, Any]
) -> str:
    """Generate a clean, professional, fully structured Markdown response."""
    if filters.get("out_of_scope"):
        return (
            "This question is outside the scope of the Instructor Database. "
            "I can only assist with queries regarding instructor records, tracks, locations, skills, experience, and availability."
        )

    if not lecturers:
        filter_descs = []
        if filters.get("track"): filter_descs.append(f"Track: **{filters['track']}**")
        if filters.get("city"): filter_descs.append(f"City: **{filters['city']}**")
        if filters.get("status"): filter_descs.append(f"Status: **{filters['status']}**")
        if filters.get("skills"): filter_descs.append(f"Skills: **{', '.join(filters['skills'])}**")
        if "min_experience" in filters: filter_descs.append(f"Experience >= **{filters['min_experience']} years**")
        if "max_experience" in filters: filter_descs.append(f"Experience <= **{filters['max_experience']} years**")
        if filters.get("name_part"): filter_descs.append(f"Name matching: **'{filters['name_part']}'**")

        filter_str = f" with {', '.join(filter_descs)}" if filter_descs else ""
        return f"No matching instructors or lecturers were found in the database{filter_str}. Please try broadening your search criteria."

    req_attr = filters.get("req_attribute")

    # 1. Single lecturer detail / contact card
    if (filters.get("name") or filters.get("name_part")) and len(lecturers) == 1:
        l = lecturers[0]
        status_badge = "Available" if l.get("status") == "available" else "Not Available"
        skills_str = ", ".join(l.get("skills", [])) or "None listed"
        phone_str = l.get("phone") or "N/A"
        email_str = l.get("email") or "N/A"

        if req_attr in ("phone", "email"):
            return (
                f"### Contact Information for {l['name']}\n\n"
                f"- **Phone:** `{phone_str}`\n"
                f"- **Email:** `{email_str}`\n"
                f"- **Track:** {l.get('track')} ({l.get('city')})\n"
                f"- **Status:** {status_badge}\n"
                f"- **Experience:** {l.get('experience_years')} years\n"
                f"- **Skills:** {skills_str}"
            )
        else:
            return (
                f"### Profile: {l['name']}\n\n"
                f"- **Track:** {l.get('track')}\n"
                f"- **City:** {l.get('city')}\n"
                f"- **Status:** {status_badge}\n"
                f"- **Experience:** {l.get('experience_years')} years\n"
                f"- **Skills:** {skills_str}\n"
                f"- **Phone:** `{phone_str}`\n"
                f"- **Email:** `{email_str}`"
            )

    # 2. Count request
    if req_attr == "count":
        names_list = "\n".join([f"- **{l['name']}** ({l.get('track')}, {l.get('city')} - {l.get('experience_years')} yrs exp)" for l in lecturers])
        return f"There are **{len(lecturers)}** instructor(s) matching your query:\n\n{names_list}"

    # 3. Experience comparison / Ranking query
    if filters.get("sort") == "experience_desc":
        top = lecturers[0]
        top_list = "\n".join([
            f"| **{l['name']}** | {l.get('track')} | {l.get('city')} | **{l.get('experience_years')} yrs** | {('Available' if l.get('status') == 'available' else 'Busy')} | {', '.join(l.get('skills', [])[:3])} |"
            for l in lecturers[:5]
        ])
        scope_str = " among the matching candidates" if len(lecturers) < 14 else " in the database"
        return (
            f"The most experienced instructor{scope_str} is **{top['name']}** with **{top.get('experience_years')} years** of experience ({top.get('track')}, {top.get('city')}).\n\n"
            f"### Top Instructors by Experience:\n\n"
            f"| Instructor | Track | City | Experience | Status | Top Skills |\n"
            f"| :--- | :--- | :--- | :--- | :--- | :--- |\n"
            f"{top_list}"
        )

    # 4. Standard listing with clean markdown table
    count = len(lecturers)
    table_rows = []
    for l in lecturers:
        status_icon = "Available" if l.get("status") == "available" else "Busy"
        skills = ", ".join(l.get("skills", [])[:4])
        phone = l.get("phone") or "-"
        table_rows.append(
            f"| **{l['name']}** | {l.get('track')} | {l.get('city')} | {status_icon} | {l.get('experience_years')} yrs | {skills} | `{phone}` |"
        )
    table_str = "\n".join(table_rows)

    criteria_desc = []
    if filters.get("track"): criteria_desc.append(f"**{filters['track']}** track")
    if filters.get("city"): criteria_desc.append(f"in **{filters['city']}**")
    if filters.get("status"): criteria_desc.append(f"(**{filters['status']}**)")
    if filters.get("skills"): criteria_desc.append(f"with skills in **{', '.join(filters['skills'])}**")
    if "min_experience" in filters: criteria_desc.append(f"with >= **{filters['min_experience']} years** exp")
    criteria_summary = " " + " ".join(criteria_desc) if criteria_desc else ""

    return (
        f"Found **{count}** matching instructor(s){criteria_summary}:\n\n"
        f"| Instructor | Track | City | Status | Experience | Skills | Phone |\n"
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        f"{table_str}"
    )


# ---------------------------------------------------------------------------
# Fallback / Deterministic High-Quality Policy Formatter
# ---------------------------------------------------------------------------
def format_policy_response_deterministic(
    question: str,
    context_chunks: List[Dict[str, Any]]
) -> str:
    """Synthesize policy chunks into a structured, cited markdown answer."""
    if not context_chunks:
        return "This topic is not covered in the currently available company policies. Please consult HR Operations."

    sections = []
    for c in context_chunks:
        ref = c.get("ref", "Policy Clause")
        raw_text = c.get("text", "").replace("\ufffd", " - ").replace("—", " - ").replace("–", " - ").strip()
        doc_title = c.get("doc_title", "Company Policy Manual")

        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        if not lines:
            continue

        first_line = lines[0]
        header_match = re.match(r"^\[(.+?)\]\s*(?:\((.+?)\))?$", first_line)

        if header_match:
            clause_header = header_match.group(1).strip()
            section_info = header_match.group(2).strip() if header_match.group(2) else ""
            body_lines = lines[1:]

            sec_part = f" - *{section_info}*" if section_info else ""
            sub_header = f"#### **{clause_header}**{sec_part}\n> **Citation:** [{ref}] {doc_title}"
        else:
            sub_header = f"#### **{ref}** - *{doc_title}*"
            body_lines = lines

        bullets = []
        for line in body_lines:
            bullets.append(f"- {line}")

        content = "\n".join(bullets) if bullets else f"- {first_line}"
        sections.append(f"{sub_header}\n\n{content}")

    formatted_sections = "\n\n---\n\n".join(sections)
    return (
        f"### Official Company Policy Guidelines\n\n"
        f"According to verified internal compliance guidelines:\n\n"
        f"{formatted_sections}\n\n"
        f"*Note: For official exceptions or operational execution, please consult the designated HR authority.*"
    )



# ---------------------------------------------------------------------------
# Main Generation Functions with Groq LLM + Deterministic Fallback
# ---------------------------------------------------------------------------
def generate_data_chat_response(
    question: str,
    lecturers: List[Dict[str, Any]],
    filters_applied: Dict[str, Any],
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Generate a strictly grounded response summarizing matching database records.
    Uses Groq LLM if available, or high-fidelity deterministic generator as fallback.
    """
    if filters_applied.get("out_of_scope"):
        return (
            "This question is outside the scope of the Instructor Database. "
            "I can only assist with queries regarding instructor records, tracks, locations, skills, experience, and availability."
        )

    client = get_groq_client()
    if not client:
        return format_data_response_deterministic(question, lecturers, filters_applied)

    if not lecturers:
        return format_data_response_deterministic(question, lecturers, filters_applied)

    lecturers_summary = "\n".join([
        f"- ID: {r.get('id')}, Name: {r.get('name')}, Track: {r.get('track')}, City: {r.get('city')}, Status: {r.get('status')}, Experience: {r.get('experience_years')} years, Skills: {', '.join(r.get('skills', []))}, Phone: {r.get('phone', 'N/A')}, Email: {r.get('email', 'N/A')}"
        for r in lecturers
    ])

    system_prompt = (
        "You are an internal HR Instructor Directory Assistant.\n\n"
        "STRICT CONSTRAINTS:\n"
        "1. GROUNDING: Answer based ONLY on the verified database records provided below.\n"
        "2. OUT-OF-SCOPE REFUSAL: If the question is outside instructor profiles (e.g. general knowledge, cooking, weather, math, code, company policies), refuse by saying:\n"
        "\"This question is outside the scope of the Instructor Database. I can only assist with queries regarding instructor records, tracks, locations, and availability.\"\n"
        "3. FORMATTING: Present answers clearly in clean Markdown. For listings, use a Markdown table with columns: Instructor, Track, City, Status, Experience, Skills, Phone. For specific contact requests, provide a concise contact summary."
    )

    messages = [{"role": "system", "content": system_prompt}]

    # Include recent turns if available
    if conversation_history:
        for turn in conversation_history[-4:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    user_content = (
        f"User Query: {question}\n\n"
        f"Filters Extracted: {filters_applied}\n\n"
        f"Verified Database Records ({len(lecturers)} match(es)):\n{lecturers_summary}\n\n"
        f"Provide a helpful, professional Markdown response based strictly on these records."
    )
    messages.append({"role": "user", "content": user_content})

    try:
        model_name = os.getenv("GROQ_MODEL", GROQ_MODEL)
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=600,
            temperature=0.0
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Groq generation failed for data chat: {e}. Using deterministic fallback.")
        return format_data_response_deterministic(question, lecturers, filters_applied)


def generate_policy_chat_response(
    question: str,
    context_chunks: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Generate a strictly grounded policy answer from retrieved context chunks.
    Uses Groq LLM if available, or high-fidelity deterministic synthesizer as fallback.
    """
    if not context_chunks:
        return "This topic is not covered in the currently available company policies. Please consult HR Operations."

    client = get_groq_client()
    if not client:
        return format_policy_response_deterministic(question, context_chunks)

    context_str = "\n\n".join([
        f"[{c.get('doc_title', 'Policy Document')} | Ref: {c.get('ref', 'N/A')}]\n{c.get('text', '')}"
        for c in context_chunks
    ])

    system_prompt = (
        "You are an Internal Compliance & Policy Assistant.\n\n"
        "STRICT GROUNDING INSTRUCTIONS:\n"
        "1. STRICT GROUNDING: Answer the user's question ONLY and EXCLUSIVELY using the provided official policy context.\n"
        "2. CITATIONS: Include the exact policy reference tag (e.g. [AG-GOV-001 §23]) for each policy rule you mention.\n"
        "3. OUT-OF-SCOPE REFUSAL: If the question cannot be answered from the policy excerpts, reply: 'This question is not covered in the official company policies.'\n"
        "4. FORMATTING: Structure your response with clear Markdown bullet points and bold headers."
    )

    messages = [{"role": "system", "content": system_prompt}]

    if conversation_history:
        for turn in conversation_history[-4:]:
            role = turn.get("role")
            content = turn.get("content")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    user_content = (
        f"User Question: {question}\n\n"
        f"Official Policy Context:\n{context_str}\n\n"
        f"Answer the question thoroughly and concisely based strictly on the context above. Include citations like [AG-GOV-001 §X]."
    )
    messages.append({"role": "user", "content": user_content})

    try:
        model_name = os.getenv("GROQ_MODEL", GROQ_MODEL)
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            max_tokens=800,
            temperature=0.0
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        logger.warning(f"Groq generation failed for policy chat: {e}. Using deterministic fallback.")
        return format_policy_response_deterministic(question, context_chunks)

import os
import re
import uuid
import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

# Load .env file at startup
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from contextlib import asynccontextmanager

from app.supabase_client import (
    fetch_lecturers,
    insert_lecturer,
    delete_lecturer,
    fetch_policies,
    delete_policy,
    match_policy_chunks_rpc,
    search_policy_chunks_keyword,
    fetch_chat_sessions,
    fetch_chat_session,
    save_chat_session,
    delete_chat_session,
    delete_all_chat_sessions,
)
from app.embeddings import semantic_search, get_embedding_model, encode_text
from app.groq_client import (
    generate_data_chat_response,
    generate_policy_chat_response,
)
from app.document_processor import (
    extract_text_from_pdf,
    extract_text_from_docx,
    ingest_document,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # App Startup: Preload and warm up embedding model
    print("[STARTUP] Preloading local multilingual embedding model...")
    try:
        model = get_embedding_model()
        if model:
            _ = model.encode(["warmup"], normalize_embeddings=True)
            print("[STARTUP] Embedding model preloaded and warm!")
        else:
            print("[STARTUP WARNING] Embedding model could not be loaded locally.")
    except Exception as e:
        print(f"[STARTUP ERROR] Failed to initialize embedding model: {e}")
    yield
    # App Shutdown
    print("[SHUTDOWN] Application shutting down.")


app = FastAPI(
    title="Internal HR AI Assistant API",
    description="""
# 🤖 Internal HR AI Assistant API

Interactive APIs for **Instructor Database Queries** and **Policies & Regulations RAG**:

* **Data Queries Chat (`POST /api/chat_data`)**: Natural language instructor search, filtering by track, city, and status.
* **Policies & Regulations Chat (`POST /api/chat_policy`)**: Semantic policy search and grounded QA with pgvector embeddings.
* **Instructor Directory (`/api/lecturers`)**: Add, list, and delete instructor records directly in Supabase.
* **Document Ingestion (`/api/documents/upload`)**: Upload PDF, Word (.docx), or TXT documents to chunk, embed, and index into Supabase pgvector.
* **Session Management (`/api/chat/sessions`)**: Full multi-turn conversation thread lifecycle.

Interactive documentation is available at `/docs` (Swagger UI) and `/redoc` (ReDoc).
""",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ---------------------------------------------------------------------------
# Schemas & Models
# ---------------------------------------------------------------------------
class ChatDataRequest(BaseModel):
    question: str = Field(
        ...,
        description="Natural language question about instructors or lecturers.",
        example="Who are the available AI lecturers in Cairo?"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session UUID to continue an ongoing conversation thread.",
        example="a57b8067-a0d6-4836-9378-81da29dceb49"
    )


class ChatDataResponse(BaseModel):
    session_id: str = Field(description="Unique conversation session UUID")
    answer: str = Field(description="Assistant's Markdown-formatted response")
    status: str = Field(description="Status of query: 'ok', 'no_results', or 'out_of_scope'")
    filters_applied: Dict[str, Any] = Field(description="Extracted search filters")
    sources: List[Dict[str, Any]] = Field(description="Matched instructor records from Supabase")
    messages: List[Dict[str, Any]] = Field(description="Full conversation history for this session")


class ChatPolicyRequest(BaseModel):
    question: str = Field(
        ...,
        description="Natural language question about company policies, rules, and regulations.",
        example="What are the rules for working hours and remote work?"
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional session UUID to continue an ongoing conversation thread.",
        example="a57b8067-a0d6-4836-9378-81da29dceb49"
    )


class ChatPolicyResponse(BaseModel):
    session_id: str = Field(description="Unique conversation session UUID")
    answer: str = Field(description="Assistant's Markdown-formatted response")
    status: str = Field(description="Status of response: 'ok' or 'not_covered'")
    citations: List[Dict[str, Any]] = Field(description="Retrieved policy citations")
    note: Optional[str] = Field(default=None, description="System disclaimer note")
    messages: List[Dict[str, Any]] = Field(description="Full conversation history for this session")


class LecturerCreate(BaseModel):
    name: str = Field(..., description="Full Name", example="Dr. Tarek Mahmoud")
    track: str = Field(..., description="Track specialization (AI, Networks, Software)", example="AI")
    city: str = Field(..., description="City location", example="Cairo")
    phone: Optional[str] = Field(default="", description="Contact Phone Number", example="01012345678")
    national_id: Optional[str] = Field(default="", description="National ID", example="29001010100099")
    email: Optional[str] = Field(default="", description="Email address", example="tarek@example.com")
    status: str = Field(default="available", description="Availability Status (available / not_available)", example="available")
    experience_years: int = Field(default=0, description="Years of experience", example=5)
    skills: List[str] = Field(default=[], description="List of technical skills", example=["Python", "PyTorch", "Computer Vision"])


# ---------------------------------------------------------------------------
# Query Parsing Helper for Data Queries
# ---------------------------------------------------------------------------
KNOWN_SKILLS = {
    "Python", "PyTorch", "Computer Vision", "NLP", "Selenium", "Cypress",
    "Postman", "PyTest", "Test Automation", "React", "Node.js", "TypeScript",
    "FastAPI", "PostgreSQL", "Cisco", "Java", "Docker", "Kubernetes", "AWS", "SQL"
}


def parse_data_query(question: str, all_lecturers: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    q = question.strip().lower()
    filters: Dict[str, Any] = {}

    # Check for obvious out-of-scope topics
    out_of_scope_patterns = [
        r"\b(weather|recipe|cake|cook|cooking|president|capital of|movie|song|joke|football|soccer|score)\b",
        r"\b(how to build a website|write (a )?python script to|debug this code|solve \d+)\b",
        r"\b(leave policy|working hours|attendance rules|probation period|severance|company regulations?)\b"
    ]
    if any(re.search(pat, q, re.I) for pat in out_of_scope_patterns):
        return {"out_of_scope": True}

    # 1. Track filter (handling database tracks: AI, Networks, Testing, Full-Stack)
    if re.search(r"\b(ai|artificial intelligence|machine learning|deep learning|data science|computer vision)\b", q, re.I):
        filters["track"] = "AI"
    elif re.search(r"\b(network(s|ing)?|cisco|ccna|infrastructure|system admin)\b", q, re.I):
        filters["track"] = "Networks"
    elif re.search(r"\b(testing|test|tester|qa|quality assurance|automation|pytest|selenium|cypress)\b", q, re.I):
        filters["track"] = "Testing"
    elif re.search(r"\b(full-?stack|fullstack|software|developer|development|frontend|backend|web dev)\b", q, re.I):
        filters["track"] = "Full-Stack"

    # 2. City filter
    if re.search(r"\bcairo\b", q, re.I):
        filters["city"] = "Cairo"
    elif re.search(r"\balexandria\b|\balex\b", q, re.I):
        filters["city"] = "Alexandria"
    elif re.search(r"\bgiza\b", q, re.I):
        filters["city"] = "Giza"

    # 3. Availability filter
    if re.search(r"\b(not available|unavailable|busy|inactive|occupied)\b", q, re.I):
        filters["status"] = "not_available"
    elif re.search(r"\b(available|free|active|open)\b", q, re.I):
        filters["status"] = "available"

    # 4. Experience filters
    more_exp = re.search(r"(?:more than|over|greater than|>)\s*(\d+)\s*(?:years?)?", q, re.I)
    at_least_exp = re.search(r"(?:at least|minimum of|>=|\+)\s*(\d+)\s*(?:years?)?|(\d+)\+\s*years?", q, re.I)
    less_exp = re.search(r"(?:less than|under|fewer than|<)\s*(\d+)\s*(?:years?)?", q, re.I)
    exact_exp = re.search(r"(\d+)\s*years?(?:\s*of)?\s*experience", q, re.I)

    if more_exp:
        filters["min_experience"] = int(more_exp.group(1)) + 1
    elif at_least_exp:
        val = at_least_exp.group(1) or at_least_exp.group(2)
        filters["min_experience"] = int(val)
    elif less_exp:
        filters["max_experience"] = int(less_exp.group(1)) - 1
    elif exact_exp:
        filters["exact_experience"] = int(exact_exp.group(1))
    elif re.search(r"\bsenior\b", q, re.I):
        filters["min_experience"] = 5
    elif re.search(r"\bjunior\b", q, re.I):
        filters["max_experience"] = 3

    if re.search(r"\b(most experience[d]?|highest experience|top experience|greatest experience|maximum experience)\b", q, re.I):
        filters["sort"] = "experience_desc"
    elif re.search(r"\b(least experience[d]?|lowest experience|minimum experience)\b", q, re.I):
        filters["sort"] = "experience_asc"

    # 5. Skills extraction
    skills_pool = set(KNOWN_SKILLS)
    if all_lecturers:
        for l in all_lecturers:
            for s in l.get("skills", []):
                skills_pool.add(s)

    matched_skills = []
    for skill in skills_pool:
        if re.search(rf"\b{re.escape(skill)}\b", q, re.I):
            matched_skills.append(skill)
    if matched_skills:
        filters["skills"] = list(dict.fromkeys(matched_skills))

    # 6. Specific lecturer name extraction
    if all_lecturers:
        for l in all_lecturers:
            name = l.get("name", "")
            if not name:
                continue
            if name.lower() in q:
                filters["name"] = name
                break
            parts = [p.lower() for p in name.split() if len(p) > 2 and p.lower() not in ("dr.", "mr.", "ms.", "ahmed", "mohamed")]
            for part in parts:
                if re.search(rf"\b{re.escape(part)}\b", q, re.I):
                    filters["name_part"] = part
                    break
            if "name_part" in filters:
                break

    # 7. Attribute / intent extraction
    if re.search(r"\b(phone|mobile|cell|call|number)\b", q, re.I):
        filters["req_attribute"] = "phone"
    elif re.search(r"\b(email|contact|reach|mail)\b", q, re.I):
        filters["req_attribute"] = "email"
    elif re.search(r"\b(how many|count|number of)\b", q, re.I):
        filters["req_attribute"] = "count"

    return filters


# ---------------------------------------------------------------------------
# 1) API: Data Queries (/api/chat_data)
# ---------------------------------------------------------------------------
@app.post(
    "/api/chat_data",
    response_model=ChatDataResponse,
    summary="Chat with Instructor Data Assistant",
    tags=["Chat - Data Queries"],
    description="Send natural language queries about instructors and lecturers (filtering by track, city, status, skills)."
)
def chat_data_endpoint(payload: ChatDataRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    existing_session = fetch_chat_session(session_id)
    messages = list(existing_session.get("messages", [])) if existing_session else []

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    messages.append({
        "role": "user",
        "content": payload.question,
        "created_at": now_iso
    })

    lecturers = fetch_lecturers()
    filters = parse_data_query(payload.question, lecturers)

    # Check if out-of-scope
    if filters.get("out_of_scope"):
        answer = generate_data_chat_response(
            question=payload.question,
            lecturers=[],
            filters_applied=filters,
            conversation_history=messages[:-1]
        )
        status = "out_of_scope"
        sources = []
    else:
        results = list(lecturers)

        # Multi-turn context resolution:
        # If user asks a follow-up ("Which of them...", "What is his phone...", "Is he available?")
        # and no specific track/city was specified, check previous turn's sources
        q_lower = payload.question.lower()
        is_follow_up = bool(re.search(r"\b(them|him|her|his|hers|which of them|he|she|they)\b", q_lower))
        if is_follow_up and messages and len(messages) >= 2:
            prev_assistant = next((m for m in reversed(messages[:-1]) if m.get("role") == "assistant" and m.get("sources")), None)
            if prev_assistant and prev_assistant.get("sources"):
                prev_ids = {s["id"] for s in prev_assistant["sources"]}
                results = [r for r in results if r.get("id") in prev_ids]

        # Apply Name filter
        if filters.get("name"):
            results = [r for r in results if filters["name"].lower() in r.get("name", "").lower()]
        elif filters.get("name_part"):
            results = [r for r in results if filters["name_part"].lower() in r.get("name", "").lower()]

        # Apply Track filter
        if filters.get("track"):
            results = [r for r in results if r.get("track", "").lower() == filters["track"].lower()]

        # Apply City filter
        if filters.get("city"):
            results = [r for r in results if r.get("city", "").lower() == filters["city"].lower()]

        # Apply Status filter
        if filters.get("status"):
            results = [r for r in results if r.get("status", "").lower() == filters["status"].lower()]

        # Apply Experience filter
        if "min_experience" in filters:
            results = [r for r in results if int(r.get("experience_years", 0)) >= filters["min_experience"]]
        if "max_experience" in filters:
            results = [r for r in results if int(r.get("experience_years", 0)) <= filters["max_experience"]]
        if "exact_experience" in filters:
            results = [r for r in results if int(r.get("experience_years", 0)) == filters["exact_experience"]]

        # Apply Skills filter
        if filters.get("skills"):
            req_skills = [s.lower() for s in filters["skills"]]
            results = [
                r for r in results
                if any(s in [sk.lower() for sk in r.get("skills", [])] for s in req_skills)
            ]

        # Apply Sorting
        if filters.get("sort") == "experience_desc":
            results.sort(key=lambda x: int(x.get("experience_years", 0)), reverse=True)
        elif filters.get("sort") == "experience_asc":
            results.sort(key=lambda x: int(x.get("experience_years", 0)))

        # Fallback keyword match if general query and no results yet
        is_general_roster = bool(re.search(r"\b(all|everyone|list|roster|instructors?|lecturers?|teachers?|trainers?|staff|who|which)\b", q_lower))
        if not filters and not is_general_roster and not is_follow_up:
            matched_by_kw = [
                r for r in results
                if any(s.lower() in q_lower for s in r.get("skills", [])) or r.get("name", "").lower() in q_lower
            ]
            if matched_by_kw:
                results = matched_by_kw
            else:
                results = []

        answer = generate_data_chat_response(
            question=payload.question,
            lecturers=results,
            filters_applied=filters,
            conversation_history=messages[:-1]
        )
        is_out_of_scope = "outside the scope" in answer.lower()
        status = "out_of_scope" if is_out_of_scope else ("ok" if results else "no_results")

        sources = []
        if not is_out_of_scope and results:
            sources = [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "track": r.get("track"),
                    "city": r.get("city"),
                    "status": r.get("status"),
                    "experience_years": r.get("experience_years"),
                    "skills": r.get("skills", []),
                    "email": r.get("email"),
                    "phone": r.get("phone"),
                }
                for r in results
            ]

    assistant_msg = {
        "role": "assistant",
        "content": answer,
        "status": status,
        "sources": sources,
        "created_at": now_iso
    }
    messages.append(assistant_msg)

    first_user_msg = next((m["content"] for m in messages if m["role"] == "user"), payload.question)
    title = existing_session.get("title") if existing_session else first_user_msg[:50]

    save_chat_session(session_id, "data", title, messages)

    return ChatDataResponse(
        session_id=session_id,
        answer=answer,
        status=status,
        filters_applied=filters,
        sources=sources,
        messages=messages
    )


@app.get(
    "/api/chat_data",
    summary="Get Data Queries History / Session",
    tags=["Chat - Data Queries"],
    description="Retrieve full conversation message turns for a given session_id, or list all data query chat sessions."
)
def get_chat_data(session_id: Optional[str] = Query(None, description="Optional session UUID to retrieve conversation history")):
    if session_id:
        session = fetch_chat_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found.")
        return {"session": session}
    return {"sessions": fetch_chat_sessions("data")}


# ---------------------------------------------------------------------------
# 2) API: Policies & Regulations (/api/chat_policy)
# ---------------------------------------------------------------------------
@app.post(
    "/api/chat_policy",
    response_model=ChatPolicyResponse,
    summary="Chat with Policies & Regulations Assistant",
    tags=["Chat - Policies & Regulations"],
    description="Send questions to search internal company policies using pgvector dense embeddings and receive grounded answers with citations."
)
def chat_policy_endpoint(payload: ChatPolicyRequest):
    session_id = payload.session_id or str(uuid.uuid4())
    existing_session = fetch_chat_session(session_id)
    messages = list(existing_session.get("messages", [])) if existing_session else []

    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    messages.append({
        "role": "user",
        "content": payload.question,
        "created_at": now_iso
    })

    # Check for obvious out-of-scope topics
    policy_out_of_scope = [
        r"\b(recipe|cook|cooking|bake|baking|pizza|cake|dough|dinner|lunch|breakfast|food)\b",
        r"\b(weather|forecast|rain|temperature|climate)\b",
        r"\b(capital of|president of|prime minister|movie|song|joke|football|soccer|score)\b",
        r"\b(how to build a website|write (a )?python script to|debug this code|solve \d+)\b"
    ]
    if any(re.search(pat, payload.question, re.I) for pat in policy_out_of_scope):
        answer = "This question is not covered in the official company policies. Please consult HR Operations or relevant documentation."
        status = "not_covered"
        citations = []
        note = "AI-generated - please consult HR Operations for unlisted policies."
        assistant_msg = {
            "role": "assistant",
            "content": answer,
            "status": status,
            "citations": citations,
            "note": note,
            "created_at": now_iso
        }
        messages.append(assistant_msg)
        first_user_msg = next((m["content"] for m in messages if m["role"] == "user"), payload.question)
        title = existing_session.get("title") if existing_session else first_user_msg[:50]
        save_chat_session(session_id, "policy", title, messages)
        return ChatPolicyResponse(
            session_id=session_id,
            answer=answer,
            status=status,
            citations=citations,
            note=note,
            messages=messages
        )

    # Contextualize query for multi-turn if follow-up
    q_text = payload.question.strip()
    if messages and len(messages) >= 2:
        last_user = next((m["content"] for m in reversed(messages[:-1]) if m.get("role") == "user"), None)
        if last_user and len(q_text.split()) <= 6 and not any(k in q_text.lower() for k in ("policy", "leave", "hours", "conduct", "travel")):
            q_text = f"{last_user} - {q_text}"

    query_vec = encode_text(q_text)
    if not query_vec:
        raise HTTPException(status_code=500, detail="Failed to compute query vector embedding.")

    # 1. Primary Vector Similarity Search via Supabase RPC
    relevant_chunks = match_policy_chunks_rpc(
        query_embedding=query_vec,
        match_threshold=0.25,
        match_count=4
    )

    # 2. Fallback Keyword Search if Vector RPC returned no results
    if not relevant_chunks:
        relevant_chunks = search_policy_chunks_keyword(payload.question, limit=4)

    if not relevant_chunks:
        answer = "This topic is not covered in the currently available company policies. Please consult HR Operations."
        status = "not_covered"
        citations = []
        note = "AI-generated - please consult HR Operations for unlisted policies."
    else:
        answer = generate_policy_chat_response(
            question=payload.question,
            context_chunks=relevant_chunks,
            conversation_history=messages[:-1]
        )
        status = "ok"
        citations = [
            {
                "doc": c.get("doc_title", "Policy Document"),
                "ref": c.get("ref", "N/A"),
                "text": c.get("text", "")
            }
            for c in relevant_chunks
        ]
        note = "AI-generated - all operational actions require designated human authorization."

    assistant_msg = {
        "role": "assistant",
        "content": answer,
        "status": status,
        "citations": citations,
        "note": note,
        "created_at": now_iso
    }
    messages.append(assistant_msg)

    first_user_msg = next((m["content"] for m in messages if m["role"] == "user"), payload.question)
    title = existing_session.get("title") if existing_session else first_user_msg[:50]

    save_chat_session(session_id, "policy", title, messages)

    return ChatPolicyResponse(
        session_id=session_id,
        answer=answer,
        status=status,
        citations=citations,
        note=note,
        messages=messages
    )


@app.get(
    "/api/chat_policy",
    summary="Get Policy Queries History / Session",
    tags=["Chat - Policies & Regulations"],
    description="Retrieve full conversation message turns for a given session_id, or list all policy query chat sessions."
)
def get_chat_policy(session_id: Optional[str] = Query(None, description="Optional session UUID to retrieve conversation history")):
    if session_id:
        session = fetch_chat_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Chat session not found.")
        return {"session": session}
    return {"sessions": fetch_chat_sessions("policy")}


# ---------------------------------------------------------------------------
# 3) Conversation Sessions Management
# ---------------------------------------------------------------------------
@app.get("/api/chat/sessions", summary="List Chat Sessions", tags=["Conversation Sessions"])
def list_chat_sessions(type: str = Query("data", description="Session type ('data' or 'policy')")):
    return {"sessions": fetch_chat_sessions(type)}


@app.get("/api/chat/sessions/{session_id}", summary="Get Session Details", tags=["Conversation Sessions"])
def get_single_session(session_id: str):
    session = fetch_chat_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session": session}


@app.delete("/api/chat/sessions/{session_id}", summary="Delete Single Session", tags=["Conversation Sessions"])
def delete_single_session_endpoint(session_id: str):
    success = delete_chat_session(session_id)
    return {"success": success, "deleted_id": session_id}


@app.delete("/api/chat/sessions", summary="Clear All Sessions", tags=["Conversation Sessions"])
def clear_all_sessions_endpoint(type: str = Query("data", description="Session type ('data' or 'policy')")):
    success = delete_all_chat_sessions(type)
    return {"success": success}


# ---------------------------------------------------------------------------
# 4) Document Ingestion (PDF, Word DOCX, TXT)
# ---------------------------------------------------------------------------
@app.post(
    "/api/documents/upload",
    summary="Upload & Ingest Policy Document",
    tags=["Document Ingestion & RAG"],
    description="Upload a PDF, Word (.docx), or TXT document (or direct raw text) to chunk, compute 384-d dense vector embeddings, and persist into Supabase pgvector."
)
async def upload_document(
    file: Optional[UploadFile] = File(default=None, description="Document file (.pdf, .docx, .doc, .txt)"),
    title: Optional[str] = Form(default=None, description="Optional document title"),
    raw_text: Optional[str] = Form(default=None, description="Optional raw document text content")
):
    text_content = ""
    doc_title = title or ""

    if file:
        filename = file.filename
        content = await file.read()
        if not doc_title:
            doc_title = Path(filename).stem.replace("_", " ").title()

        if filename.lower().endswith(".pdf"):
            text_content = extract_text_from_pdf(content)
        elif filename.lower().endswith((".docx", ".doc")):
            text_content = extract_text_from_docx(content)
        else:
            try:
                text_content = content.decode("utf-8")
            except Exception:
                text_content = content.decode("latin-1", errors="ignore")
    elif raw_text:
        text_content = raw_text.strip()
        if not doc_title:
            doc_title = "Manual Policy Document"
    else:
        raise HTTPException(status_code=400, detail="Please upload a file or provide text content.")

    if not text_content.strip():
        raise HTTPException(status_code=400, detail="Document content is empty or could not be extracted.")

    result = ingest_document(title=doc_title, text=text_content)
    return result


@app.get("/api/documents", summary="List Ingested Policy Documents", tags=["Document Ingestion & RAG"])
def list_documents():
    return {"documents": fetch_policies()}


@app.delete("/api/documents/{doc_id}", summary="Delete Ingested Policy Document", tags=["Document Ingestion & RAG"])
def remove_document(doc_id: str):
    delete_policy(doc_id)
    return {"success": True, "deleted_doc_id": doc_id}


# ---------------------------------------------------------------------------
# 5) Instructor Management (CRUD on Supabase)
# ---------------------------------------------------------------------------
@app.get("/api/lecturers", summary="List All Instructors", tags=["Instructor Directory"])
def list_lecturers():
    return {"lecturers": fetch_lecturers()}


@app.post("/api/lecturers", summary="Add New Instructor", tags=["Instructor Directory"])
def create_lecturer(payload: LecturerCreate):
    created = insert_lecturer(payload.dict())
    return {"success": True, "lecturer": created}


@app.delete("/api/lecturers/{lecturer_id}", summary="Delete Instructor", tags=["Instructor Directory"])
def remove_lecturer(lecturer_id: int):
    delete_lecturer(lecturer_id)
    return {"success": True, "deleted_id": lecturer_id}


# ---------------------------------------------------------------------------
# Static Web App & Index
# ---------------------------------------------------------------------------
FRONTEND_DIR = BASE_DIR / "static"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))

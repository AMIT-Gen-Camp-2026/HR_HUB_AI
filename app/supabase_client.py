import os
import re
import logging
import requests
from typing import List, Dict, Any, Optional

logger = logging.getLogger("supabase_client")

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://giwwiktvxwvtdasorpwj.supabase.co")
SUPABASE_ANON_KEY = os.getenv(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imdpd3dpa3R2eHd2dGRhc29ycHdqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgyNzU1NTAsImV4cCI6MjEwMzg1MTU1MH0.4_TqoS1BJ2rsuAhgWQm25vjNyJWm01u9hvEck0uOJH0"
)

HEADERS = {
    "apikey": SUPABASE_ANON_KEY,
    "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}


# ---------------------------------------------------------------------------
# Lecturers / Instructors (Supabase Only)
# ---------------------------------------------------------------------------
def fetch_lecturers() -> List[Dict[str, Any]]:
    """Fetch lecturers directly from Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/lecturers?select=*&order=id.asc"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Could not fetch lecturers from Supabase: {e}")
    return []


def insert_lecturer(data: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a new lecturer directly into Supabase."""
    payload = {
        "name": data.get("name", "").strip(),
        "track": data.get("track", "AI").strip(),
        "city": data.get("city", "Cairo").strip(),
        "phone": data.get("phone", "").strip(),
        "national_id": data.get("national_id", "").strip(),
        "email": data.get("email", "").strip(),
        "status": data.get("status", "available").strip(),
        "experience_years": int(data.get("experience_years", 0)),
        "skills": data.get("skills", []),
    }
    if data.get("id"):
        payload["id"] = data["id"]

    try:
        url = f"{SUPABASE_URL}/rest/v1/lecturers"
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=5)
        if resp.status_code in [200, 201]:
            created = resp.json()
            if isinstance(created, list) and len(created) > 0:
                return created[0]
        elif resp.status_code == 409:
            # Identity sequence collision recovery
            existing = fetch_lecturers()
            next_id = max([r.get("id", 0) for r in existing], default=0) + 1
            payload["id"] = next_id
            resp2 = requests.post(url, headers=HEADERS, json=payload, timeout=5)
            if resp2.status_code in [200, 201]:
                created = resp2.json()
                if isinstance(created, list) and len(created) > 0:
                    return created[0]
    except Exception as e:
        logger.error(f"Could not insert lecturer into Supabase: {e}")

    return payload


def delete_lecturer(lecturer_id: int) -> bool:
    """Delete a lecturer directly from Supabase."""
    try:
        url = f"{SUPABASE_URL}/rest/v1/lecturers?id=eq.{lecturer_id}"
        resp = requests.delete(url, headers=HEADERS, timeout=5)
        return resp.status_code in [200, 204]
    except Exception as e:
        logger.error(f"Could not delete lecturer {lecturer_id} from Supabase: {e}")
        return False


# ---------------------------------------------------------------------------
# Policies & Policy Chunks (Supabase Vector Store Only)
# ---------------------------------------------------------------------------
def fetch_policies() -> List[Dict[str, Any]]:
    """Fetch policy document headers directly from Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/policies?select=*&order=id.asc"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Could not fetch policies from Supabase: {e}")
    return []


def insert_policy_document(doc_id: str, title: str, paragraphs_count: int) -> Dict[str, Any]:
    """Insert or update policy metadata in Supabase policies table."""
    record = {
        "doc_id": doc_id,
        "title": title,
        "paragraphs_count": paragraphs_count
    }
    try:
        url = f"{SUPABASE_URL}/rest/v1/policies"
        requests.post(url, headers=HEADERS, json=record, timeout=5)
    except Exception as e:
        logger.error(f"Could not insert policy metadata {doc_id} into Supabase: {e}")
    return record


def insert_policy_chunks(chunks: List[Dict[str, Any]], batch_size: int = 30) -> bool:
    """Insert chunks with dense vector embeddings into Supabase policy_chunks table in safe batches."""
    if not chunks:
        return True

    success = True
    url = f"{SUPABASE_URL}/rest/v1/policy_chunks"
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        try:
            resp = requests.post(url, headers=HEADERS, json=batch, timeout=15)
            if resp.status_code not in [200, 201]:
                logger.warning(f"Supabase returned status {resp.status_code} for chunks batch {i}-{i+len(batch)}: {resp.text}")
                success = False
        except Exception as e:
            logger.error(f"Could not insert policy chunks batch {i}-{i+len(batch)}: {e}")
            success = False

    return success


def clean_ref_string(ref: str) -> str:
    """Normalize and clean chunk reference tags."""
    if not ref:
        return "N/A"
    clean = ref.replace("\ufffd", "§").replace("?", "§")
    clean = re.sub(r"§+", "§", clean)
    return clean


def search_policy_chunks_keyword(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Fallback text search across policy chunks in Supabase for distinct domain terms."""
    import re
    # Extract significant keywords (exclude common generic words)
    stop_words = {
        "what", "when", "where", "which", "who", "whom", "this", "that", "these", "those",
        "have", "has", "had", "does", "doing", "would", "should", "could", "ought",
        "make", "made", "like", "know", "take", "tell", "give", "want", "find", "need",
        "policy", "rules", "regulations", "about", "with", "from", "into", "over",
        "some", "such", "than", "them", "then", "there", "they", "just", "also"
    }
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 3 and w not in stop_words]
    if not words:
        return []

    results = []
    for word in words[:2]:
        url = f"{SUPABASE_URL}/rest/v1/policy_chunks?text=ilike.*{word}*&select=id,doc_id,doc_title,ref,text&limit={limit}"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=6)
            if resp.status_code == 200:
                for item in resp.json():
                    if not any(r["id"] == item["id"] for r in results):
                        item["ref"] = clean_ref_string(item.get("ref", ""))
                        item["similarity"] = 0.40
                        results.append(item)
                    if len(results) >= limit:
                        break
        except Exception as e:
            logger.warning(f"Keyword search failed for word '{word}': {e}")
        if len(results) >= limit:
            break

    return results[:limit]


def match_policy_chunks_rpc(
    query_embedding: List[float],
    match_threshold: float = 0.25,
    match_count: int = 4
) -> List[Dict[str, Any]]:
    """Query Supabase directly using PostgreSQL match_policy_chunks vector RPC."""
    url = f"{SUPABASE_URL}/rest/v1/rpc/match_policy_chunks"
    payload = {
        "query_embedding": query_embedding,
        "match_threshold": match_threshold,
        "match_count": match_count
    }
    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=8)
        if resp.status_code == 200:
            results = resp.json()
            if isinstance(results, list):
                for r in results:
                    r["ref"] = clean_ref_string(r.get("ref", ""))
                return results
        else:
            logger.warning(f"match_policy_chunks RPC returned {resp.status_code}: {resp.text}")
    except Exception as e:
        logger.error(f"Supabase pgvector RPC query failed: {e}")
    return []


def delete_policy(doc_id: str) -> bool:
    """Delete a policy document and its vector chunks directly from Supabase."""
    try:
        url_chunks = f"{SUPABASE_URL}/rest/v1/policy_chunks?doc_id=eq.{doc_id}"
        requests.delete(url_chunks, headers=HEADERS, timeout=5)
        url_doc = f"{SUPABASE_URL}/rest/v1/policies?doc_id=eq.{doc_id}"
        requests.delete(url_doc, headers=HEADERS, timeout=5)
        return True
    except Exception as e:
        logger.error(f"Could not delete policy {doc_id} from Supabase: {e}")
        return False


# ---------------------------------------------------------------------------
# Multi-Turn Chat Sessions (Supabase with In-Memory Ephemeral Fallback)
# ---------------------------------------------------------------------------
_in_memory_sessions: Dict[str, Dict[str, Any]] = {}


def fetch_chat_sessions(session_type: str) -> List[Dict[str, Any]]:
    """Fetch all chat sessions for a given type ('data' or 'policy') from Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/chat_sessions?type=eq.{session_type}&order=updated_at.desc"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data
    except Exception as e:
        logger.warning(f"Could not fetch chat sessions from Supabase: {e}")

    # In-memory ephemeral fallback (no disk/data files created)
    matching = [s for s in _in_memory_sessions.values() if s.get("type") == session_type]
    matching.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return matching


def fetch_chat_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single chat session by ID directly from Supabase."""
    url = f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
    except Exception as e:
        logger.warning(f"Could not fetch session {session_id} from Supabase: {e}")

    # In-memory ephemeral fallback
    return _in_memory_sessions.get(session_id)


def save_chat_session(session_id: str, session_type: str, title: str, messages: list) -> Dict[str, Any]:
    """Upsert a multi-turn chat session directly into Supabase."""
    import datetime
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    record = {
        "id": session_id,
        "type": session_type,
        "title": title[:60],
        "messages": messages,
        "updated_at": now_iso
    }

    # Save to in-memory runtime cache
    _in_memory_sessions[session_id] = record

    # Sync to Supabase
    try:
        url = f"{SUPABASE_URL}/rest/v1/chat_sessions"
        upsert_headers = dict(HEADERS)
        upsert_headers["Prefer"] = "resolution=merge-duplicates"
        requests.post(url, headers=upsert_headers, json=record, timeout=5)
    except Exception as e:
        logger.warning(f"Could not save chat session {session_id} to Supabase: {e}")

    return record


def delete_chat_session(session_id: str) -> bool:
    """Delete a single chat session directly from Supabase."""
    _in_memory_sessions.pop(session_id, None)
    try:
        url = f"{SUPABASE_URL}/rest/v1/chat_sessions?id=eq.{session_id}"
        resp = requests.delete(url, headers=HEADERS, timeout=5)
        return resp.status_code in [200, 204]
    except Exception as e:
        logger.error(f"Could not delete session {session_id} from Supabase: {e}")
        return False


def delete_all_chat_sessions(session_type: str) -> bool:
    """Delete all chat sessions of a given type directly from Supabase."""
    keys_to_remove = [k for k, v in _in_memory_sessions.items() if v.get("type") == session_type]
    for k in keys_to_remove:
        _in_memory_sessions.pop(k, None)

    try:
        url = f"{SUPABASE_URL}/rest/v1/chat_sessions?type=eq.{session_type}"
        resp = requests.delete(url, headers=HEADERS, timeout=5)
        return resp.status_code in [200, 204]
    except Exception as e:
        logger.error(f"Could not clear {session_type} sessions from Supabase: {e}")
        return False


# Backward-compatible aliases
def log_data_chat(*args, **kwargs): pass
def get_data_chat_history(*args, **kwargs): return []
def delete_all_data_chats(): return delete_all_chat_sessions("data")
def delete_data_chat_item(msg_id: str): return delete_chat_session(msg_id)
def log_policy_chat(*args, **kwargs): pass
def get_policy_chat_history(*args, **kwargs): return []
def delete_all_policy_chats(): return delete_all_chat_sessions("policy")
def delete_policy_chat_item(msg_id: str): return delete_chat_session(msg_id)

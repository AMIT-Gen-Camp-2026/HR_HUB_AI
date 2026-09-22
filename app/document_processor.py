import io
import re
import logging
from typing import List, Dict, Any

from app.supabase_client import (
    fetch_policies,
    insert_policy_document,
    insert_policy_chunks,
)
from app.embeddings import encode_texts

logger = logging.getLogger("document_processor")


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from PDF bytes using pypdf."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        pages_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages_text.append(text.strip())
        return "\n\n".join(pages_text)
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}")
        return ""


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract plain text from DOCX bytes using python-docx."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        paragraphs = []
        for p in doc.paragraphs:
            txt = p.text.strip()
            if txt:
                paragraphs.append(txt)
        for table in doc.tables:
            for row in table.rows:
                row_txt = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_txt:
                    paragraphs.append(row_txt)
        return "\n\n".join(paragraphs)
    except Exception as e:
        logger.error(f"Error extracting text from DOCX: {e}")
        return ""


def chunk_text(raw_text: str, doc_id: str, max_chunk_words: int = 160) -> List[Dict[str, str]]:
    """
    Split text into semantically cohesive policy chunks with numbered reference IDs.
    Binds section headers and clause identifiers directly to their substantive body text
    to prevent orphan heading chunks and guarantee high search relevance.
    """
    cleaned = raw_text.replace("\r\n", "\n").strip()
    raw_lines = [line.strip() for line in cleaned.split("\n") if line.strip()]

    policy_chunks = []
    current_section = ""
    current_clause = ""
    current_body = []
    chunk_index = 1

    def flush_clause(sec: str, clause: str, body: List[str]):
        nonlocal chunk_index
        if not body:
            return

        clause_code_match = re.search(r"[A-Z]{2,4}-[A-Z]{2,5}-\d{3}", clause)
        code_tag = f" ({clause_code_match.group(0)})" if clause_code_match else ""

        header_line = ""
        if clause and sec:
            header_line = f"[{clause}] ({sec})\n"
        elif clause:
            header_line = f"[{clause}]\n"
        elif sec:
            header_line = f"[{sec}]\n"

        full_content = "\n".join(body)
        words = full_content.split()
        if len(words) <= max_chunk_words:
            policy_chunks.append({
                "ref": f"{doc_id} §{chunk_index}{code_tag}",
                "text": (header_line + full_content).strip()
            })
            chunk_index += 1
        else:
            for i in range(0, len(words), max_chunk_words):
                sub_text = " ".join(words[i:i + max_chunk_words])
                policy_chunks.append({
                    "ref": f"{doc_id} §{chunk_index}{code_tag}",
                    "text": (header_line + sub_text).strip()
                })
                chunk_index += 1

    for line in raw_lines:
        sec_match = re.match(r"^(\d{1,2})\.\s+([A-Za-z0-9,\s&]+)$", line) or re.match(r"^(Section\s+\d{1,2}[:.]?\s*.+)$", line, re.I)
        clause_match = re.match(r"^([A-Z]{2,4}-[A-Z]{2,5}-\d{3})\s*[–—\-•\s]\s*(.+)$", line)
        is_toc_or_index = bool(re.match(r"^[A-Z]{2,4}-[A-Z]{2,5}-\d{3}\s*[–—\-•\s].+[–—\-•\s]\s*\d{1,2}\.", line))

        if is_toc_or_index:
            continue

        if sec_match and len(line.split()) <= 12:
            flush_clause(current_section, current_clause, current_body)
            current_body = []
            current_clause = ""
            current_section = line
        elif clause_match and len(line.split()) <= 12:
            flush_clause(current_section, current_clause, current_body)
            current_body = []
            current_clause = line
        else:
            current_body.append(line)

    flush_clause(current_section, current_clause, current_body)

    # Fallback for plain unstructured text documents
    if not policy_chunks:
        raw_paragraphs = [p.strip() for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
        for p in raw_paragraphs:
            words = p.split()
            if len(words) <= max_chunk_words:
                policy_chunks.append({
                    "ref": f"{doc_id} §{chunk_index}",
                    "text": p
                })
                chunk_index += 1
            else:
                for i in range(0, len(words), max_chunk_words):
                    sub_p = " ".join(words[i:i + max_chunk_words])
                    policy_chunks.append({
                        "ref": f"{doc_id} §{chunk_index}",
                        "text": sub_p
                    })
                    chunk_index += 1

    return policy_chunks


def ingest_document(title: str, text: str, doc_id: str = None) -> Dict[str, Any]:
    """
    Ingest a document: chunk it, compute vector embeddings, and store strictly into Supabase
    'policies' (document metadata) and 'policy_chunks' (vector store). Zero local file storage.
    """
    existing_policies = fetch_policies()

    if not doc_id:
        doc_id = f"POL-{len(existing_policies) + 1:02d}"

    doc_title = title.strip() or f"Policy Document {doc_id}"
    raw_chunks = chunk_text(text, doc_id)

    if not raw_chunks:
        return {
            "success": False,
            "error": "No valid text chunks found to ingest."
        }

    # 1. Generate dense vector embeddings for each chunk
    chunk_texts = [c["text"] for c in raw_chunks]
    embeddings = encode_texts(chunk_texts)

    if embeddings is None:
        logger.warning("Batch encoding failed, attempting sequential chunk encoding...")
        from app.embeddings import encode_text
        embeddings_list = []
        for txt in chunk_texts:
            vec = encode_text(txt)
            embeddings_list.append(vec if vec else [0.0] * 384)
    else:
        embeddings_list = [emb.tolist() for emb in embeddings]

    chunks_with_embeddings = []
    for i, c in enumerate(raw_chunks):
        emb_list = embeddings_list[i] if i < len(embeddings_list) else [0.0] * 384
        chunks_with_embeddings.append({
            "doc_id": doc_id,
            "doc_title": doc_title,
            "ref": c["ref"],
            "text": c["text"],
            "embedding": emb_list
        })

    # 2. Persist parent document metadata directly to Supabase
    insert_policy_document(
        doc_id=doc_id,
        title=doc_title,
        paragraphs_count=len(chunks_with_embeddings)
    )

    # 3. Persist chunks with their dense vector embeddings directly to Supabase in batches
    insert_policy_chunks(chunks_with_embeddings, batch_size=30)

    return {
        "success": True,
        "doc_id": doc_id,
        "title": doc_title,
        "paragraphs_count": len(chunks_with_embeddings),
        "chunks": [
            {"ref": c["ref"], "text": c["text"]}
            for c in chunks_with_embeddings
        ]
    }

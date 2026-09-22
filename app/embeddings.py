import os
import logging
import numpy as np
from typing import List, Dict, Any, Optional

logger = logging.getLogger("embeddings")

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_MODEL_DIR = BASE_DIR / "models" / "embedding_model"

# Default small, high-performance multilingual model (~120MB, supports English, Arabic, and 50+ languages)
DEFAULT_MODEL_NAME = os.getenv(
    "EMBEDDING_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

_model_instance = None


def get_embedding_model():
    """
    Load the local multilingual embedding model.
    If the project's models/ folder does not exist or is empty, it automatically
    creates the directory, downloads the model, and saves it locally for future offline use.
    """
    global _model_instance
    if _model_instance is None:
        try:
            from sentence_transformers import SentenceTransformer
            model_name = os.getenv("EMBEDDING_MODEL_NAME", DEFAULT_MODEL_NAME)

            # Check if model files already exist locally in models/embedding_model
            has_local_weights = (
                LOCAL_MODEL_DIR.exists() and (
                    (LOCAL_MODEL_DIR / "model.safetensors").exists() or
                    (LOCAL_MODEL_DIR / "pytorch_model.bin").exists() or
                    (LOCAL_MODEL_DIR / "modules.json").exists()
                )
            )

            if has_local_weights:
                logger.info(f"Loading embedding model from project directory: {LOCAL_MODEL_DIR}")
                print(f"[EMBEDDINGS] Loading model from local directory: {LOCAL_MODEL_DIR}")
                _model_instance = SentenceTransformer(str(LOCAL_MODEL_DIR))
            else:
                logger.info(f"Local model not found. Creating {LOCAL_MODEL_DIR} and downloading '{model_name}'...")
                print(f"[EMBEDDINGS] models/ folder not found. Creating directory and downloading '{model_name}'...")
                LOCAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)
                _model_instance = SentenceTransformer(model_name)
                
                # Save downloaded weights and tokenizer into models/ folder
                print(f"[EMBEDDINGS] Saving model to local directory: {LOCAL_MODEL_DIR} for future offline use...")
                _model_instance.save(str(LOCAL_MODEL_DIR))
                print(f"[EMBEDDINGS] Model successfully saved to {LOCAL_MODEL_DIR}!")

            logger.info("Embedding model loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            print(f"[EMBEDDINGS ERROR] Failed to load or download embedding model: {e}")
            _model_instance = None
    return _model_instance


def encode_text(text: str) -> Optional[List[float]]:
    """Generate a dense vector embedding for a single string."""
    model = get_embedding_model()
    if model is None:
        return None
    try:
        embedding = model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return embedding.tolist()
    except Exception as e:
        logger.error(f"Error encoding text: {e}")
        return None


def encode_texts(texts: List[str]) -> Optional[np.ndarray]:
    """Generate dense vector embeddings for a list of strings."""
    model = get_embedding_model()
    if model is None:
        return None
    try:
        embeddings = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return embeddings
    except Exception as e:
        logger.error(f"Error encoding texts: {e}")
        return None


def semantic_search(query: str, chunks: List[Dict[str, Any]], top_k: int = 3, threshold: float = 0.25) -> List[Dict[str, Any]]:
    """
    Search chunks using local multilingual embeddings and cosine similarity.
    Each chunk dict is expected to have 'text' and optionally 'embedding'.
    """
    if not chunks:
        return []

    model = get_embedding_model()
    if model is None:
        # Fallback to token keyword overlap if model cannot be loaded
        return _fallback_keyword_search(query, chunks, top_k)

    try:
        query_vec = model.encode(query, convert_to_numpy=True, normalize_embeddings=True)

        texts = [c.get("text", "") for c in chunks]
        chunk_vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

        # Dot product of normalized vectors = Cosine similarity
        similarities = np.dot(chunk_vecs, query_vec)

        scored_chunks = []
        for idx, score in enumerate(similarities):
            if score >= threshold:
                scored_chunks.append({
                    "chunk": chunks[idx],
                    "score": float(score)
                })

        scored_chunks.sort(key=lambda x: x["score"], reverse=True)
        return [item["chunk"] for item in scored_chunks[:top_k]]
    except Exception as e:
        logger.warning(f"Semantic search failed, falling back to keyword search: {e}")
        return _fallback_keyword_search(query, chunks, top_k)


def _fallback_keyword_search(query: str, chunks: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
    import re
    q_words = set(re.findall(r"\w+", query.lower()))
    scored = []
    for c in chunks:
        text = c.get("text", "")
        p_words = set(re.findall(r"\w+", text.lower()))
        overlap = len(q_words & p_words)
        if overlap > 0:
            scored.append((overlap, c))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]

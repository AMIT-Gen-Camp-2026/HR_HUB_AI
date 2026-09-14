"""Typed settings, loaded once from environment (.env in dev, real env vars in prod).
Imported by app/main.py at startup — never re-read per-request. get_settings() is
cached so every part of the app sees the exact same Settings instance."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- provider selection ---
    provider: Literal["api", "hf", "local", "stub"] = "stub"

    # --- Gemini ---
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash-lite"  # see docs/DECISIONS.md section 18
    gemini_grounding_model: str = "gemini-3.6-flash"
    gemini_timeout_seconds: int = 60

    # --- web search evidence ---
    tavily_api_key: str = ""
    search_provider: Literal["gemini_grounding", "tavily", "none"] = "tavily"
    tavily_max_results: int = 5
    enable_academic_search: bool = True
    academic_max_results: int = 3
    
    
    # --- embeddings ---
    # REVISED DECISION (see docs/DECISIONS.md section 17): originally a local
    # Hugging Face model, switched to Gemini's hosted embedding model after the
    # local model proved impractical to set up reliably (large download, slow
    # first load, environment-specific issues). Trade-off accepted: embeddings
    # now share the same free-tier data-usage caveat as text generation, and
    # consume from the same Gemini quota. embedding_model/device/hf_* are kept
    # for anyone who wants to switch PROVIDER=hf back to local embeddings later.
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_device: str = "cpu"
    hf_token: str = ""
    hf_mode: Literal["local_transformers", "inference_api"] = "local_transformers"
    gemini_embedding_model: str = "gemini-embedding-001"
    
    

    # --- local LLM ---
    local_base_url: str = "http://localhost:11434/v1"
    local_model: str = "qwen2.5:7b-instruct"

    # --- feature flags ---
    feature_image_analysis: bool = False
    feature_web_grounding: bool = True

    # --- free-tier guardrails (docs/DECISIONS.md section 6) ---
    daily_request_cap: int = 1200
    gemini_call_pacing_seconds: float = 8.0  # delay between consecutive Gemini calls, see docs/DECISIONS.md section 18
    claim_batch_size: int = 5
    claim_extraction_batch_size: int = 4

    # --- flask ---
    api_port: int = 8100
    log_level: str = "INFO"

    @property
    def prompts_dir(self) -> Path:
        return PROJECT_ROOT / "app" / "prompts" / "templates"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

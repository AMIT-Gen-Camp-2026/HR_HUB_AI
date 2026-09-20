"""
config/settings.py

مسؤول عن قراءة كل إعدادات المشروع من ملف .env بشكل مركزي.
باقي الملفات هتستورد من هنا بدل ما تقرأ os.environ بنفسها في أماكن متفرقة.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    
    # ============================================================
    # Service-to-service auth (app/security/auth.py)
    # ============================================================
    # ثابت بين الـ ai-service وأي حد بيناديه (غالبًا الـ full-stack backend).
    # لو سايبه فاضي، الـ endpoints بتفضل شغالة من غير حماية - مقبول للتطوير
    # المحلي بس، خطر لو السيرفر متاح لغير جهازك.
    AI_SERVICE_API_KEY: str = os.getenv("AI_SERVICE_API_KEY", "")

    # Semantic judge providers. Empty keys disable that provider in the chain.
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    GEMINI_JUDGE_MODEL: str = os.getenv("GEMINI_JUDGE_MODEL", "gemini-3.6-flash")
    GROQ_JUDGE_MODEL: str = os.getenv("GROQ_JUDGE_MODEL", "openai/gpt-oss-120b")
    OPENROUTER_JUDGE_MODEL: str = os.getenv(
        "OPENROUTER_JUDGE_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
    )
    GROQ_BASE_URL: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    OPENROUTER_BASE_URL: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
    )
    OPENROUTER_SITE_URL: str = os.getenv("OPENROUTER_SITE_URL", "http://localhost")
    JUDGE_TIMEOUT_SECONDS: int = int(os.getenv("JUDGE_TIMEOUT_SECONDS", "60"))

    CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
    CACHE_MAX_ENTRIES: int = int(os.getenv("CACHE_MAX_ENTRIES", "128"))
    
    # ============================================================
    # Extraction Settings & Multi-Provider Support
    # ============================================================
    EXTRACTION_PROVIDER: str = os.getenv("EXTRACTION_PROVIDER", "auto")
    GEMINI_EXTRACTION_MODEL: str = os.getenv(
        "GEMINI_EXTRACTION_MODEL", "gemini-3.6-flash"
    )
    GROQ_EXTRACTION_MODEL: str = os.getenv(
        "GROQ_EXTRACTION_MODEL", "openai/gpt-oss-120b"
    )
    OPENROUTER_EXTRACTION_MODEL: str = os.getenv(
        "OPENROUTER_EXTRACTION_MODEL", "meta-llama/llama-3.3-70b-instruct"
    )

    # ============================================================
    # Hugging Face
    # ============================================================
    HF_API_TOKEN: str = os.getenv("HF_API_TOKEN", "")

    # سلسلة الموديلات بالترتيب - لو الأول فشل بسبب quota/rate-limit
    # (402 Payment Required / 429 Too Many Requests)، بنجرب اللي بعده.
    MODEL_CHAIN: list[dict[str, str]] = [
        {
            "repo_id": os.getenv("HF_MODEL_ID_1", "Qwen/Qwen2.5-3B-Instruct"),
            "provider": os.getenv("HF_PROVIDER_1", "featherless-ai"),
        },
        {
            "repo_id": os.getenv("HF_MODEL_ID_2", "mistralai/Mistral-7B-Instruct-v0.2"),
            "provider": os.getenv("HF_PROVIDER_2", "featherless-ai"),
        },
    ]

    # ============================================================
    # Flask
    # ============================================================
    FLASK_DEBUG: bool = os.getenv("FLASK_DEBUG", "False").lower() == "true"
    FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))

    # ============================================================
    # Upload settings
    # ============================================================
    UPLOAD_FOLDER: str = os.getenv("UPLOAD_FOLDER", "data")
    ALLOWED_EXTENSIONS = {".pdf", ".docx"}
    MAX_CONTENT_LENGTH: int = 10 * 1024 * 1024  # 10MB

    # ============================================================
    # Model generation settings
    # ============================================================
    MAX_NEW_TOKENS: int = int(os.getenv("MAX_NEW_TOKENS", "4096"))
    MODEL_TIMEOUT_SECONDS: int = int(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))

    # ============================================================
    # Feature flags (kill switch لكل feature - قاعدة رقم 6 في README.md)
    # ============================================================
    RANKING_ENABLED: bool = os.getenv("RANKING_ENABLED", "True").lower() == "true"

    @property
    def JUDGE_MODEL_CHAIN(self) -> list[dict[str, str]]:
        return [
            {"provider": "gemini", "model": self.GEMINI_JUDGE_MODEL},
            {"provider": "groq", "model": self.GROQ_JUDGE_MODEL},
            {"provider": "openrouter", "model": self.OPENROUTER_JUDGE_MODEL},
        ]

    @classmethod
    def validate(cls) -> None:
        """بتتأكد إن الإعدادات الأساسية ومفتاح واحد على الأقل موجود قبل ما نشغّل السيرفر."""
        has_any_key = bool(
            cls.GEMINI_API_KEY
            or cls.GROQ_API_KEY
            or cls.OPENROUTER_API_KEY
            or cls.HF_API_TOKEN
        )
        if not has_any_key:
            raise RuntimeError(
                "لم يتم العثور على أي API Key للموديل. تأكد من إعداد أحد المفاتيح التالية في .env: "
                "GEMINI_API_KEY أو GROQ_API_KEY أو OPENROUTER_API_KEY أو HF_API_TOKEN"
            )


config = Config()


# ============================================================
# Embedding settings (app/providers/embeddings.py بيستخدمها في
# semantic_fit() - جزء من الـ ranking pipeline الشغال فعليًا).
#
# ملحوظة تنضيف: الكلاس ده كان في الأصل جزء من "Settings" أكبر بكتير
# (Sprint 2 - FastAPI + provider abstraction) اللي اتشالت لأنها مكنتش
# متوصّلة/شغالة. سيبنا بس الحقلين اللي embeddings.py فعليًا محتاجهم.
# ============================================================

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # "local" = sentence-transformers على جهازك (زي ما كان).
    # "api"   = أي مزود متوافق مع OpenAI embeddings API (Gemini، OpenAI، إلخ).
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")

    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")

    # إعدادات مزود الـ API (لما embedding_provider="api")
    embedding_api_base_url: str = Field(
        default="https://generativelanguage.googleapis.com/v1beta/openai/",
        alias="EMBEDDING_API_BASE_URL",
    )
    embedding_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    embedding_api_model: str = Field(default="gemini-embedding-001", alias="EMBEDDING_API_MODEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
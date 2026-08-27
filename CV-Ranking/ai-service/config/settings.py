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
    # Hugging Face
    # ============================================================
    HF_API_TOKEN: str = os.getenv("HF_API_TOKEN", "")

    # سلسلة الموديلات بالترتيب - لو الأول فشل بسبب quota/rate-limit
    # (402 Payment Required / 429 Too Many Requests)، بنجرب اللي بعده.
    #
    # مهم: كل (repo_id, provider) لازم يكونوا متأكدين إنهم متاحين مع بعض
    # فعليًا على HF Inference Providers. تأكد من صفحة الموديل على
    # huggingface.co (تبويب "Inference Providers") قبل ما تضيف عنصر هنا -
    # الدعم ده بيتغير مع الوقت (مثال: Mistral-7B-Instruct-v0.3 مش مدعوم
    # بأي provider حاليًا، لكن v0.2 مدعوم عن طريق Featherless AI).
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
    MAX_NEW_TOKENS: int = int(os.getenv("MAX_NEW_TOKENS", "2048"))
    MODEL_TIMEOUT_SECONDS: int = int(os.getenv("MODEL_TIMEOUT_SECONDS", "60"))

    # ============================================================
    # Feature flags (kill switch لكل feature - قاعدة رقم 6 في README.md)
    # ============================================================
    RANKING_ENABLED: bool = os.getenv("RANKING_ENABLED", "True").lower() == "true"

    @classmethod
    def validate(cls) -> None:
        """بتتأكد إن الإعدادات الأساسية موجودة قبل ما نشغّل السيرفر."""
        if not cls.HF_API_TOKEN:
            raise RuntimeError(
                "HF_API_TOKEN مش موجود. تأكد إنك حاطط التوكن بتاعك في ملف .env "
                "بالشكل ده: HF_API_TOKEN=hf_xxxxxxxxxxxx"
            )
        if not cls.MODEL_CHAIN:
            raise RuntimeError(
                "MODEL_CHAIN فاضية - لازم يكون فيه موديل واحد على الأقل."
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
    embedding_api_key: str = Field(default="", alias="EMBEDDING_API_KEY")
    embedding_api_model: str = Field(default="gemini-embedding-001", alias="EMBEDDING_API_MODEL")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
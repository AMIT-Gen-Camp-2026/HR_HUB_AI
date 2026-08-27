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

    # Video transcription settings. The ASR model is loaded only on first use.
    VIDEO_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
    VIDEO_MAX_SIZE_MB: int = int(os.getenv("VIDEO_MAX_SIZE_MB", "200"))
    VIDEO_MAX_SIZE_BYTES: int = VIDEO_MAX_SIZE_MB * 1024 * 1024
    # "small" is multilingual; unlike the *.en checkpoints it supports Arabic and English.
    VIDEO_ASR_MODEL: str = os.getenv("VIDEO_ASR_MODEL", "small")
    VIDEO_ASR_DEVICE: str = os.getenv("VIDEO_ASR_DEVICE", "auto")
    VIDEO_ASR_COMPUTE_TYPE: str = os.getenv("VIDEO_ASR_COMPUTE_TYPE", "auto")

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
# --- الجزء الجديد (Sprint 2) ---
#
# الملفات الجديدة (app/api/routes_cv.py, routes_ranking.py,
# app/providers/factory.py, api_provider.py, local_provider.py,
# app/providers/embeddings.py, tests/conftest.py) بتستورد Settings
# و get_settings() و get_features() من هنا. الكلاس ده مضاف *جنب*
# Config القديمة، مش بدالها - main.py القديم (Flask) لسه بيستخدم
# Config زي ما هو وميتأثرش خالص.
# ============================================================

from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Features(BaseSettings):
    """كل feature معاه kill switch - القاعدة رقم 6 في README.md."""

    cv_parsing: bool = Field(default=True, alias="FEATURE_CV_PARSING")
    ranking: bool = Field(default=True, alias="FEATURE_RANKING")
    assistant: bool = Field(default=False, alias="FEATURE_ASSISTANT")  # Sprint 3 - لسه مقفول

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


class Settings(BaseSettings):
    """
    إعدادات العالم الجديد (FastAPI + provider abstraction).
    كل الحقول ليها default معقول عشان الـ tests تشتغل حتى من غير .env
    (زي ما providers.yaml بيقول: الـ stub هو default التيست والـ UI).
    """

    # dev | staging | production - بيتحط في /health عشان يبان بسرعة إنت شغال فين
    app_env: str = Field(default="dev", alias="APP_ENV")

    # أي provider شغال دلوقتي: api | hf | local | stub
    provider: str = Field(default="stub", alias="PROVIDER")

    # --- Scenario 1: api ---
    api_key: str = Field(default="", alias="API_KEY")
    api_base_url: str = Field(default="https://api.openai.com/v1", alias="API_BASE_URL")
    api_model: str = Field(default="gpt-4o-mini", alias="API_MODEL")
    api_timeout_seconds: int = Field(default=60, alias="API_TIMEOUT_SECONDS")

    # --- Scenario 3: local (Ollama/vLLM) ---
    local_model: str = Field(default="qwen2.5:7b-instruct", alias="LOCAL_MODEL")
    local_base_url: str = Field(default="http://localhost:11434/v1", alias="LOCAL_BASE_URL")
    local_timeout_seconds: int = Field(default=120, alias="LOCAL_TIMEOUT_SECONDS")

    # --- Embeddings (self-hosted دايمًا - راجع app/providers/embeddings.py) ---
    embedding_model: str = Field(default="BAAI/bge-m3", alias="EMBEDDING_MODEL")
    embedding_device: str = Field(default="cpu", alias="EMBEDDING_DEVICE")

    # --- Prompts ---
    prompts_dir: str = Field(default="app/prompts/templates", alias="PROMPTS_DIR")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_features() -> Features:
    return Features()

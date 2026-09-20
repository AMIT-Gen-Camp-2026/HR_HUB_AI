"""
app/providers/hf_provider.py

مسؤول عن التواصل مع الموديلات لاستخراج بيانات الـ CV (Extraction)
مع دعم Fallback تلقائي متعدد المزودين (Multi-Provider Fallback):
Gemini, Groq, OpenRouter, و Hugging Face Inference Providers.
"""

import logging
from typing import Callable, TypeVar

import httpx
from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError

from config.settings import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ModelInferenceError(Exception):
    """بترفع لو حصلت أي مشكلة أثناء استدعاء الموديل (شبكة، auth، rate limit، quota، إلخ)."""
    pass


# Cache للـ clients بتوع Hugging Face
_hf_clients: dict[str, InferenceClient] = {}


def _get_hf_client(provider: str) -> InferenceClient:
    """بترجع نسخة مشتركة من InferenceClient لكل provider في Hugging Face."""
    if provider not in _hf_clients:
        if not config.HF_API_TOKEN:
            raise ModelInferenceError(
                "HF_API_TOKEN مش موجود في .env"
            )
        _hf_clients[provider] = InferenceClient(
            provider=provider,
            api_key=config.HF_API_TOKEN,
            timeout=config.MODEL_TIMEOUT_SECONDS,
        )
    return _hf_clients[provider]


def _call_gemini(model: str, system_prompt: str, user_prompt: str) -> str:
    """استدعاء Google Gemini API بنمط JSON مباشر."""
    if not config.GEMINI_API_KEY:
        raise ModelInferenceError("GEMINI_API_KEY غير متوفر في .env")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "system_instruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.0,
            "seed": 42,
            "responseMimeType": "application/json",
        },
    }

    try:
        with httpx.Client(timeout=config.MODEL_TIMEOUT_SECONDS) as client:
            response = client.post(
                url,
                headers={"x-goog-api-key": config.GEMINI_API_KEY},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        raise ModelInferenceError(f"فشل الاتصال بـ Gemini ({model}): {e}") from e


def _call_openai_compatible(
    provider_name: str,
    model: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
    user_prompt: str,
    extra_headers: dict[str, str] | None = None,
) -> str:
    """استدعاء أي مزود متوافق مع OpenAI chat completions (Groq / OpenRouter)."""
    if not api_key:
        raise ModelInferenceError(f"مفتاح {provider_name.upper()}_API_KEY غير متوفر.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "seed": 42,
        "response_format": {"type": "json_object"},
    }

    try:
        with httpx.Client(timeout=config.MODEL_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        raise ModelInferenceError(f"فشل الاتصال بـ {provider_name} ({model}): {e}") from e


def _call_hf(repo_id: str, provider: str, system_prompt: str, user_prompt: str) -> str:
    """استدعاء Hugging Face Inference Providers."""
    client = _get_hf_client(provider)

    try:
        response = client.chat.completions.create(
            model=repo_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=config.MAX_NEW_TOKENS,
            response_format={"type": "json_object"},
            temperature=0.0,
            seed=42,
        )
    except HfHubHTTPError as e:
        raise ModelInferenceError(f"فشل الاتصال بـ {repo_id} عبر {provider}: {e}") from e
    except Exception as e:
        raise ModelInferenceError(f"خطأ غير متوقع من {repo_id} عبر {provider}: {e}") from e

    if not response.choices:
        raise ModelInferenceError(f"{repo_id} رجّع response فاضي (بدون choices).")

    content = response.choices[0].message.content
    if not content:
        raise ModelInferenceError(f"{repo_id} رجّع محتوى فاضي.")

    return content


def _call_model(repo_id: str, provider: str, system_prompt: str, user_prompt: str) -> str:
    """
    نقطة الاستدعاء الموحدة التي توجه الطلب للمزود المطلوب:
    - provider == "gemini": Google Gemini API
    - provider == "groq": Groq API
    - provider == "openrouter": OpenRouter API
    - أي مزود آخر: Hugging Face Inference Provider
    """
    if provider == "gemini":
        return _call_gemini(repo_id, system_prompt, user_prompt)
    elif provider == "groq":
        return _call_openai_compatible(
            "groq", repo_id, config.GROQ_BASE_URL, config.GROQ_API_KEY, system_prompt, user_prompt
        )
    elif provider == "openrouter":
        return _call_openai_compatible(
            "openrouter",
            repo_id,
            config.OPENROUTER_BASE_URL,
            config.OPENROUTER_API_KEY,
            system_prompt,
            user_prompt,
            {"HTTP-Referer": config.OPENROUTER_SITE_URL, "X-Title": "HR Hub AI"},
        )
    else:
        return _call_hf(repo_id, provider, system_prompt, user_prompt)


def _build_model_chain() -> list[dict[str, str]]:
    """يبني سلسلة الموديلات بناءً على التفضيل والمفاتيح المتوفرة."""
    pref = (getattr(config, "EXTRACTION_PROVIDER", "auto") or "auto").lower().strip()

    if pref == "hf":
        return list(config.MODEL_CHAIN)
    elif pref == "gemini" and config.GEMINI_API_KEY:
        chain = [{"repo_id": config.GEMINI_EXTRACTION_MODEL, "provider": "gemini"}]
        if config.GROQ_API_KEY:
            chain.append({"repo_id": config.GROQ_EXTRACTION_MODEL, "provider": "groq"})
        return chain
    elif pref == "groq" and config.GROQ_API_KEY:
        chain = [{"repo_id": config.GROQ_EXTRACTION_MODEL, "provider": "groq"}]
        if config.GEMINI_API_KEY:
            chain.append({"repo_id": config.GEMINI_EXTRACTION_MODEL, "provider": "gemini"})
        return chain
    elif pref == "openrouter" and config.OPENROUTER_API_KEY:
        return [{"repo_id": config.OPENROUTER_EXTRACTION_MODEL, "provider": "openrouter"}]

    # Auto mode: build fallback chain across available providers
    chain: list[dict[str, str]] = []
    if config.GEMINI_API_KEY:
        chain.append({"repo_id": getattr(config, "GEMINI_EXTRACTION_MODEL", "gemini-3.6-flash"), "provider": "gemini"})
    if config.GROQ_API_KEY:
        chain.append({"repo_id": getattr(config, "GROQ_EXTRACTION_MODEL", "openai/gpt-oss-120b"), "provider": "groq"})
    if config.OPENROUTER_API_KEY:
        chain.append({"repo_id": getattr(config, "OPENROUTER_EXTRACTION_MODEL", "meta-llama/llama-3.3-70b-instruct"), "provider": "openrouter"})
    if config.HF_API_TOKEN and config.MODEL_CHAIN:
        chain.extend(config.MODEL_CHAIN)

    return chain or list(config.MODEL_CHAIN)


def query_model(
    system_prompt: str,
    user_prompt: str,
    validate_fn: Callable[[str], T] | None = None,
    metadata: dict[str, object] | None = None,
) -> T | str:
    """
    بتبعت الـ prompts للموديل الأساسي، ولو فشل (اتصال، حصة/quota، أو validation)
    بتجرب المزود التالي في السلسلة تلقائيًا.

    Args:
        system_prompt: الـ system prompt.
        user_prompt: الـ user prompt.
        validate_fn: دالة اختيارية للتحقق من الناتج وتحويله لـ schema.
        metadata: قاموس لتسجيل الموديل والمزود المستخدم وعدد المحاولات.
    """
    chain = _build_model_chain()
    if not chain:
        raise ModelInferenceError("MODEL_CHAIN فاضية ومفيش أي API key متوفر.")

    attempt_order = list(chain)
    if len(chain) == 1:
        attempt_order.append(chain[0])

    if metadata is not None:
        metadata.clear()
        metadata.update(
            {
                "model_used": None,
                "provider": None,
                "attempt_number": None,
                "fallback_occurred": False,
            }
        )

    last_error: Exception | None = None

    for attempt_num, model_cfg in enumerate(attempt_order, start=1):
        repo_id = model_cfg["repo_id"]
        provider = model_cfg["provider"]

        try:
            logger.info(
                "محاولة %d/%d: %s عبر %s",
                attempt_num, len(attempt_order), repo_id, provider,
            )
            content = _call_model(repo_id, provider, system_prompt, user_prompt)

            if validate_fn is not None:
                try:
                    result = validate_fn(content)
                except Exception as validation_error:
                    logger.warning(
                        "محاولة %d (%s عبر %s): الموديل رد لكن الـ output فشل "
                        "في الـ validation: %s",
                        attempt_num, repo_id, provider, validation_error,
                    )
                    last_error = validation_error
                    continue
            else:
                result = content

            if attempt_num > 1:
                logger.warning(
                    "تم الرد بنجاح من %s (%s) بعد %d محاولة/محاولات فاشلة",
                    repo_id, provider, attempt_num - 1,
                )
            if metadata is not None:
                metadata.update(
                    {
                        "model_used": repo_id,
                        "provider": provider,
                        "attempt_number": attempt_num,
                        "fallback_occurred": attempt_num > 1,
                    }
                )
            return result

        except ModelInferenceError as e:
            logger.warning("فشلت المحاولة %d (%s عبر %s): %s", attempt_num, repo_id, provider, e)
            last_error = e
            continue

    raise ModelInferenceError(
        f"فشلت كل محاولات الاتصال بالموديلات ({len(attempt_order)} محاولة). "
        f"آخر خطأ: {last_error}"
    ) from last_error
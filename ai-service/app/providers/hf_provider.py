"""
models/qwen_model.py

الملف الوحيد في المشروع اللي "بيعرف" إزاي نتكلم مع الموديل فعليًا.
باقي المشروع (services/, app.py) بيتكلم مع الدالة query_model() بس،
وميعرفش تفاصيل إن إحنا بنستخدم Hugging Face Inference Providers،
ولا إن فيه أكتر من موديل واحد بيتم المحاولة عليهم.

--- Multi-Model Fallback ---
جهازنا شغال على Inference Providers سحابية (مش موديل محلي)، وده معناه
إننا عرضة لـ rate limits / quota errors / انقطاع مؤقت في provider معين.
عشان كده config.MODEL_CHAIN بيحتوي على أكتر من موديل بالترتيب، ولو موديل
فشل لأي سبب (rate limit، auth، timeout، أي استثناء) بننتقل للي بعده في
السلسلة تلقائيًا. آخر محاولة بتكون إعادة محاولة الموديل الأساسي (Primary)
تاني - على فرض إن المشكلة كانت مؤقتة وخلصت.

--- تحديث: الفشل بيشمل دلوقتي فشل الـ output نفسه، مش بس فشل الاتصال ---
في الأول، الـ chain كانت بتعتبر المحاولة "نجحت" بمجرد ما الموديل يرد بأي
نص، حتى لو النص ده JSON تالف/مبتور. المشكلة إن ده معناه لو الموديل
الأساسي (الأصغر عادةً) رجّع output غير صالح، النظام كان بيفشل على طول
من غير ما يجرب باقي السلسلة - يعني الـ fallback مكنش بيتفعّل فعليًا في
أكتر الحالات اللي محتاجينه فيها.

دلوقتي query_model() بتاخد validate_fn اختيارية: لو اتبعتت، بيتم تطبيقها
على output كل موديل، ولو فشلت (رمت أي Exception)، بيتم اعتبار المحاولة
دي فاشلة والانتقال للموديل اللي بعده - بالظبط زي فشل الاتصال تمامًا.
"""

import logging
from typing import Callable, TypeVar

from huggingface_hub import InferenceClient
from huggingface_hub.errors import HfHubHTTPError

from config.settings import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


class ModelInferenceError(Exception):
    """بترفع لو حصلت أي مشكلة أثناء استدعاء الموديل (شبكة، auth، rate limit، إلخ)."""
    pass


# Cache للـ clients - واحد لكل provider (مش لكل موديل، لإن provider واحد
# ممكن يخدم أكتر من موديل بنفس الـ client)
_clients: dict[str, InferenceClient] = {}


def _get_client(provider: str) -> InferenceClient:
    """بترجع نسخة مشتركة من InferenceClient لكل provider (lazy, cached)."""
    if provider not in _clients:
        if not config.HF_API_TOKEN:
            raise ModelInferenceError(
                "HF_API_TOKEN مش موجود. تأكد من ملف .env"
            )
        _clients[provider] = InferenceClient(
            provider=provider,  # صريح، مش "auto" - راجع ملحوظة الموديل القديم
            api_key=config.HF_API_TOKEN,
            timeout=config.MODEL_TIMEOUT_SECONDS,
        )
    return _clients[provider]


def _call_model(repo_id: str, provider: str, system_prompt: str, user_prompt: str) -> str:
    """
    محاولة واحدة لاستدعاء موديل واحد بعينه.
    """
    client = _get_client(provider)

    try:
        response = client.chat.completions.create(
            model=repo_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=config.MAX_NEW_TOKENS,
            temperature=0.0,
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


def query_model(
    system_prompt: str,
    user_prompt: str,
    validate_fn: Callable[[str], T] | None = None,
) -> T | str:
    """
    بتبعت الـ prompts للموديل الأساسي، ولو فشل (اتصال أو validation) بتجرب
    اللي بعده في config.MODEL_CHAIN، وآخر حاجة بتعيد محاولة الأساسي تاني.

    ترتيب المحاولات (لسلسلة من موديلين): Primary -> Fallback -> Primary (retry)

    Args:
        system_prompt: الـ system prompt.
        user_prompt: الـ user prompt.
        validate_fn: دالة اختيارية بتاخد الـ raw content النصي من الموديل
            وترجع أي حاجة (مثلاً dict بعد parsing + validation). لو رمت
            Exception، المحاولة دي بتتحسب فاشلة زي فشل الاتصال بالظبط،
            وبننتقل للموديل اللي بعده في السلسلة. لو مبعتتش، بترجع النص
            الخام زي ما هو (السلوك القديم).

    Returns:
        لو فيه validate_fn: نتيجة استدعاءها الناجح.
        لو مفيش: النص الخام من الموديل.

    Raises:
        ModelInferenceError: لو فشلت كل المحاولات (اتصال أو validation).
    """
    chain = config.MODEL_CHAIN
    if not chain:
        raise ModelInferenceError("MODEL_CHAIN فاضية - مفيش موديل نجرب عليه.")

    attempt_order = list(chain) + [chain[0]]

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
                    "تم الرد بنجاح من %s بعد %d محاولة/محاولات فاشلة",
                    repo_id, attempt_num - 1,
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
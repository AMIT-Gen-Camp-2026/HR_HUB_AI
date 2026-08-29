"""
scripts/check_embeddings.py

سكريبت تحقق سريع مستقل - بيتأكد إن EMBEDDING_PROVIDER شغال زي ما هو متوقع
(local أو api) قبل ما نكمل شغل على باقي الـ pipeline.

الاستخدام (من جوه ai-service/):
    python -m scripts.check_embeddings

بيعمل 3 حاجات:
  1. يطبع الإعدادات الحالية (من غير ما يطبع الـ API key كامل).
  2. يبعت طلب embedding حقيقي لجملتين متشابهتين وجملة مختلفة تمامًا.
  3. يتأكد إن cosine similarity للجملتين المتشابهتين أعلى بكتير من
     الجملة المختلفة - ده أهم اختبار فعلي إن الموديل شغال صح مش بس
     بيرجع أرقام عشوائية.
"""
from __future__ import annotations

import sys

from config.settings import get_settings
from app.providers.embeddings import embed, _cosine_similarity  # noqa: E402


def main() -> int:
    s = get_settings()

    print("=" * 60)
    print("Embedding config")
    print("=" * 60)
    print(f"EMBEDDING_PROVIDER   = {s.embedding_provider}")
    if s.embedding_provider == "api":
        masked_key = (
            (s.embedding_api_key[:7] + "..." + s.embedding_api_key[-4:])
            if s.embedding_api_key
            else "(EMPTY)"
        )
        print(f"EMBEDDING_API_BASE_URL = {s.embedding_api_base_url}")
        print(f"EMBEDDING_API_MODEL    = {s.embedding_api_model}")
        print(f"EMBEDDING_API_KEY      = {masked_key}")
        if not s.embedding_api_key:
            print("\n[FAIL] EMBEDDING_API_KEY فاضي. حطه في .env وجرب تاني.")
            return 1
    else:
        print(f"EMBEDDING_MODEL  = {s.embedding_model}")
        print(f"EMBEDDING_DEVICE = {s.embedding_device}")

    print("\n" + "=" * 60)
    print("Calling the embedding provider...")
    print("=" * 60)

    similar_a = "Senior Python backend engineer with strong FastAPI and PostgreSQL experience"
    similar_b = "Backend developer skilled in Python, FastAPI, and relational databases"
    different = "Pastry chef specializing in French desserts and wedding cakes"

    try:
        vectors = embed([similar_a, similar_b, different])
    except Exception as e:  # noqa: BLE001 - نريد نطبع أي خطأ بوضوح هنا
        print(f"\n[FAIL] الاتصال بالـ embedding provider فشل:\n{e}")
        return 1

    if any(len(v) == 0 for v in vectors):
        print("\n[FAIL] رجع vector فاضي - فيه مشكلة في الاستجابة.")
        return 1

    dim = len(vectors[0])
    print(f"\n[OK] رجع {len(vectors)} vectors بطول {dim} لكل واحد.")

    sim_related = _cosine_similarity(vectors[0], vectors[1])
    sim_unrelated = _cosine_similarity(vectors[0], vectors[2])

    print(f"\ncosine(similar_a, similar_b)  = {sim_related:.4f}   (متوقع: قريب من 1)")
    print(f"cosine(similar_a, different)  = {sim_unrelated:.4f}   (متوقع: أقل بوضوح)")

    if sim_related <= sim_unrelated:
        print(
            "\n[FAIL] الموديل رجع أرقام لكن المنطق غلط - الجملتين المتشابهتين "
            "المفروض يكون التشابه بينهم أعلى من الجملة المختلفة تمامًا. "
            "راجع EMBEDDING_API_MODEL/EMBEDDING_API_BASE_URL."
        )
        return 1

    print("\n[PASS] الـ embedding provider شغال ومنطقي (semantic ranking صحيح).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
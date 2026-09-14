# Applicant Presentation AI — Project Decisions Document

> هذا الملف يوثق كل القرارات التقنية والمعمارية التي تم الاتفاق عليها أثناء مرحلة التخطيط، قبل بدء التنفيذ الفعلي للكود.

---

## 1. نظرة عامة على المشروع

نظام AI يقوم بتحليل عرض تقديمي (PowerPoint) مقدّم من متقدم للوظيفة قبل المقابلة/الديمو التقني.

**الهدف الأساسي:** النظام **لا يتخذ قرار توظيف نهائي**. هو أداة دعم قرار (Decision Support Tool) — يستخرج الادعاءات (claims) من العرض، يحاول التحقق منها، ويُخرج تقرير JSON مُفصّل يُرسل إلى مسؤول الموارد البشرية (HR)، وهو من يتخذ القرار النهائي (Accepted / Rejected) بعد قراءة التقرير.

المشروع هذا (**Presentation AI**) يُبنى بالتوازي مع مشروع آخر (**Demo AI**) يحلل الديمو الفعلي/الصوت. في النهاية سيتم عمل **Integration** بين الاثنين لحساب "Consistency Score" نهائي (Phase 3 لاحقًا).

---

## 2. نطاق المشروع (Scope)

- **Input:** ملف PowerPoint (`.pptx`) فقط. لا يوجد رفع ملفات إضافية (لا evaluation reports ولا dataset docs) — **قرار مؤكد**: المتقدم يرفع الـ presentation بس.
- **لا يشمل:** تحليل الصوت أو الفيديو (ده جزء من مشروع Demo AI المنفصل).
- **اللغة:** النظام يجب أن يدعم العربي، الإنجليزي، والمزيج بينهما في نفس العرض.

---

## 3. الفكرة الجوهرية: تقسيم الـ Claims لمسارين

هذا هو القرار الأهم في المشروع، لأن مصدر الـ evidence مختلف تمامًا بين النوعين.

### المسار الأول: Objective / General Knowledge Claims
ادعاءات عن معلومات عامة معروفة، مش خاصة بمشروع المتقدم الشخصي.

أمثلة:
- "Prolog is a low-level language" ❌ (هذا خطأ فعلي — Prolog لغة عالية المستوى)
- "PostgreSQL supports JSON columns"
- "FastAPI is built on Starlette"

**طريقة التحقق:** يجب أن تعتمد **إلزاميًا** على بحث خارجي حقيقي (Web Search / Grounding)، وليس على "معرفة" الموديل الداخلية فقط. أي حكم `contradicted` أو `supported` يجب أن يكون مرفقًا بمصدر (URL) فعلي.

### المسار الثاني: Project-Specific Claims
ادعاءات خاصة بمشروع المتقدم الشخصي، لا يوجد أي مصدر خارجي يستطيع تأكيدها أو نفيها (لأن المتقدم لن يرفع ملفات إضافية).

أمثلة:
- "Our CNN model achieved 96% accuracy"
- "The dataset contains 50,000 images"

**طريقة التحقق:** **لا يوجد fact-checking حقيقي ممكن هنا.** بدلاً من ذلك، يُستخدم نظام **Plausibility Flag** (تفصيل في القسم 5).

---

## 4. الـ Claim Status النهائي (بعد التعديل)

```text
supported              → معلومة عامة تم تأكيدها من مصدر خارجي موثوق (المسار الأول فقط)
contradicted           → معلومة عامة أثبت البحث الخارجي خطأها (المسار الأول فقط)
project_unsupported    → claim خاص بمشروع المتقدم، لا يوجد أي مؤشر غرابة (المسار الثاني)
plausibility_flag      → claim خاص بمشروع المتقدم، الرقم/الادعاء يبدو غير معتاد ويستحق انتباه HR (المسار الثاني)
unclear                → الجملة غامضة، لا يمكن تفسيرها بثقة كافية
not_checkable          → claim غير قابل للتحقق أصلاً (رأي شخصي، تعميم عام)
```

**ملاحظة مهمة:** `plausibility_flag` ليس حكمًا بالخطأ، بل إشارة "يستحق سؤال في المقابلة". يجب ألا يُعامل في السكور بنفس وزن `contradicted`.

---

## 5. منطق الـ Plausibility Flag (للمسار الثاني)

نظام من طبقتين:

### أ) قواعد ثابتة (Hard Rules) — Deterministic، بدون LLM
```text
- أي metric (accuracy/precision/recall/F1) = 100% بالضبط → flag دائمًا
- أرقام "دائرية" جدًا بشكل مبالغ (99.9%, 100%, 0% error) → flag
- claim بدون أي سياق (لا يوجد ذكر لحجم الداتا، عدد classes، إلخ) → flag تلقائي
```

### ب) تقييم سياقي (Contextual Judgment) — عبر LLM
الـ threshold لا يجب أن يكون رقمًا ثابتًا واحدًا لكل الحالات، لأنه يعتمد على:
- نوع المهمة (classification / regression / detection / NLP)
- نوع الموديل المذكور (Random Forest مقابل Deep Learning/CNN)
- حجم وصعوبة الداتا المذكورة
- وجود benchmark معروف (MNIST, ImageNet, إلخ)

**القرار:** لا نضع أرقام ثابتة يدوية (زي "فوق 97%"). بدلاً من ذلك، الـ LLM نفسه (اللي عنده معرفة بالنطاقات المعتادة) يُطلب منه الحكم على السياق، **مع إلزامه بإرجاع سبب واضح لحكمه** (مش flag/no-flag بس)، حتى يفهم HR سبب العلامة.

### الناتج المتوقع في التقرير للـ HR
قسم مخصص باسم **"أسئلة مقترحة للمقابلة"** يُبنى تلقائيًا من كل الـ claims التي عليها `plausibility_flag`. هذا يحوّل الأداة من "كاشف أخطاء" إلى "مساعد تحضير للمقابلة".

---

## 6. اختيار الموديلات (AI Stack)

| المهمة | الموديل المُختار | السبب |
|---|---|---|
| استخراج/تصنيف الـ claims (الأكثر تكرارًا) | **Gemini Flash** (عبر Google AI Studio، Free Tier) | حد يومي سخي (حتى ~1500 طلب/يوم)، مجاني تمامًا |
| Fact-checking للمسار الأول (يحتاج بحث خارجي) | **Gemini Flash + Google Search Grounding Tool** (مدمجة في نفس الـ API) | لا حاجة لبناء web search integration منفصل |
| توليد الـ correction + الـ plausibility judgment | **Gemini Flash** | نفس الموديل، يكفي لمستوى الاستدلال المطلوب |
| تحليل الصور/المخططات (Phase 2 لاحقًا) | **Gemini Flash** (نفس الموديل، multimodal) | لا حاجة لموديل OCR/Vision منفصل |
| Embeddings (البحث الدلالي / evidence matching) | **موديل مفتوح المصدر من Hugging Face، يعمل محليًا (Local)** — مثل `intfloat/multilingual-e5-large` | مجاني تمامًا، بدون rate limit، يدعم العربي والإنجليزي، والبيانات لا تغادر السيرفر (لا مشاكل خصوصية) |

### تنبيه خصوصية مهم
Gemini Free Tier قد يستخدم المدخلات/المخرجات في تدريب الموديل. هذا مقبول في **مرحلة البناء والاختبار** ببيانات تجريبية. عند التعامل مع بيانات متقدمين حقيقيين في الإنتاج، يجب الانتقال لـ Paid Tier أو Vertex AI (لا يستخدم البيانات في التدريب). الكود يجب أن يُبنى بحيث يسهل تبديل الموديل/الخطة لاحقًا (عدم الاعتماد الشديد على تفاصيل خاصة بـ Gemini).

### تقدير استهلاك الـ Free Tier
لعرض تقديمي من 15 سلايد (~30 claim):
- بدون batching: ~32 استدعاء/عرض → حوالي 46 عرض/يوم كحد أقصى محافظ
- مع batching (تجميع claims في استدعاء واحد): ~7-8 استدعاءات/عرض → حوالي 187 عرض/يوم

القيد الحقيقي هو **RPM (طلبات/دقيقة)** وليس التوكنز. الحل: معالجة **Async** (رفع → "processing..." → نتيجة لاحقًا)، وليس معالجة فورية في الوقت الحقيقي (متوافق مع أن الـ MVP لا يحتاج real-time processing).

---

## 7. مبدأ تقسيم المعالجة: Deterministic مقابل AI

لا يجب استخدام AI في كل خطوة. الفصل كالتالي:

**معالجة Deterministic (بدون AI):**
```text
PPTX parsing / Slide numbering / Text extraction / Table extraction
File validation / JSON validation / Score calculation
القواعد الثابتة (Hard Rules) في الـ Plausibility Flag
```

**معالجة تحتاج AI:**
```text
Claim extraction / Claim classification / Semantic interpretation
Fact-check reasoning (المسار الأول) / Plausibility judgment (المسار الثاني)
Correction generation
```

---

## 8. الـ Pipeline الكامل

```text
Applicant Presentation (.pptx)
        │
        ▼
File Validation (Deterministic)
        │
        ▼
Content Extraction — نص / جداول / صور (Deterministic)
        │
        ▼
Content Normalization / Cleaning (Deterministic)
        │
        ▼
Claim Extraction (Gemini Flash — batched)
        │
        ▼
Claim Classification + Importance (Gemini Flash)
        │
        ▼
        ├── المسار الأول: Objective Claims ──────┐
        │        │                                │
        │        ▼                                │
        │   Web Search / Google Grounding          │
        │        │                                │
        │        ▼                                │
        │   Fact Checking (supported/contradicted) │
        │                                          │
        └── المسار الثاني: Project-Specific Claims ┤
                 │                                 │
                 ▼                                 │
            Hard Rules Check (Deterministic)       │
                 │                                 │
                 ▼                                 │
            Contextual Plausibility Judgment (LLM) │
                 │                                 │
                 ▼                                 │
     (project_unsupported / plausibility_flag) ────┘
        │
        ▼
Correction Generation (evidence-based, للمسار الأول فقط)
        │
        ▼
Severity Assignment (critical/high/medium/low)
        │
        ▼
Scoring (Overall / Fact Accuracy / Evidence Coverage / Claim Reliability)
        │
        ▼
Report Generation
        │
        ├── JSON Report (المخرج الوحيد المطلوب — تم التأكيد)
        │
        └── قسم "أسئلة مقترحة للمقابلة" (من claims عليها plausibility_flag)
        │
        ▼
Output → إلى HR (القرار النهائي Accepted/Rejected من الإنسان)
        │
        ▼
Presentation Claims (normalized) → تُحفظ لاستخدامها لاحقًا في Integration مع Demo AI (Phase 3)
```

---

## 9. Evidence Hierarchy (للمسار الأول فقط)

```text
1. Official documentation (لغة برمجة / framework / DB رسمي)
2. مصادر أكاديمية/مرجعية معتمدة
3. مصادر تقنية موثوقة معروفة
4. مصادر عامة أخرى (ثقة أقل → يميل الحكم لـ unclear بدل contradicted القاطع)
```

قاعدة الثقة: حكم `contradicted` بثقة عالية يتطلب مصدر قوي (المستويين 1-2) + ثقة عالية من الموديل. أي شيء أقل من ذلك → `unclear` ويحتاج مراجعة بشرية، وليس حكمًا قاطعًا.

---

## 10. الـ Output Format — قرار مؤكد

**JSON فقط.** لا حاجة لواجهة أو PDF في هذه المرحلة. الـ JSON يُقرأ من نظام HR أو من نظام آخر لاحقًا.

هيكل عام متوقع (بناءً على الأساس الموجود في المستند الأصلي، مع التعديلات المتفق عليها):

```json
{
  "analysis_id": "ANL-...",
  "status": "completed",
  "presentation": {
    "filename": "...",
    "slide_count": 0
  },
  "scores": {
    "overall": 0,
    "fact_accuracy": 0,
    "evidence_coverage": 0,
    "claim_reliability": 0
  },
  "summary": {
    "total_claims": 0,
    "supported": 0,
    "contradicted": 0,
    "project_unsupported": 0,
    "plausibility_flag": 0,
    "unclear": 0,
    "not_checkable": 0
  },
  "claims": [],
  "issues": [],
  "suggested_interview_questions": []
}
```

---

## 11. اللغة (Multilingual Support)

- الموديل الأساسي (Gemini) يدعم العربي والإنجليزي بشكل جيد، فلا مشكلة كبيرة في claim extraction / fact-checking.
- **يجب** أن يكون الـ embedding model **multilingual** فعليًا (مثل `intfloat/multilingual-e5-large`)، وليس إنجليزي فقط.
- التأكد من الـ UTF-8 encoding الصحيح أثناء استخراج النص من ملف الـ pptx.

---

## 12. التخزين (Storage) — قرار مؤجل

**لم يُحسم بعد.** الخيارات المطروحة للنقاش لاحقًا:
1. Stateless (بدون تخزين، النتيجة تُرجع فورًا وتنتهي)
2. تخزين مؤقت لفترة محددة (مقترح مبدئي، غير مؤكد)
3. تخزين دائم (سجل تاريخي كامل)

**ملاحظة:** يجب مراعاة قسم "Security" في المستند الأصلي (حماية بيانات المتقدم) بغض النظر عن القرار النهائي.

---

## 13. Scale المتوقع

غير محدد بدقة بعد. القرار الحالي: البدء بـ Gemini Free Tier والتصميم بطريقة تسمح بالتبديل السهل إلى Paid Tier لاحقًا إذا زاد الحجم عن الحد اليومي للـ Free Tier.

---

## 14. التكامل مع Demo AI (Phase 3)

- يُبنى **بالتوازي (Parallel)** مع مشروع Presentation AI، وليس بعده.
- الـ Integration بين المشروعين يتم **في نهاية المرحلتين**.
- **الأهمية العملية الآن:** يجب تصميم الـ **Normalized Claim Schema** (`subject / property / value / unit`) بعناية من البداية، حتى تسهل عملية المقارنة مع مخرجات Demo AI لاحقًا دون الحاجة لإعادة هيكلة البيانات.

مثال على الـ normalized claim:
```json
{
  "claim_id": "CLM-001",
  "subject": "model",
  "property": "accuracy",
  "value": 95,
  "unit": "%",
  "text": "Our model achieved 95% accuracy.",
  "slide_number": 8
}
```

---

## 15. نقاط مفتوحة لم تُحسم بعد

- [ ] استراتيجية التخزين النهائية (القسم 12)
- [ ] الحجم المتوقع الدقيق (Scale) وتأثيره على قرار الانتقال لـ Paid Tier
- [ ] الأرقام/الحدود الدقيقة داخل الـ Hard Rules في الـ Plausibility Flag (سيتم ضبطها بعد الاختبار على بيانات حقيقية)
- [ ] تفاصيل الـ prompt الدقيقة لكل من: claim extraction، fact-checking، plausibility judgment

---

---

## 16. Language convention for code, logs, and error messages (confirmed decision)

**All code comments, log messages, error messages, and any text printed to the
terminal/console must be in English — always, with no exceptions.**

This applies to:
- Code comments and docstrings (already established from the start)
- `app/errors.py` exception messages
- `app/telemetry.py` log lines
- Test output / print statements in scripts
- Any diagnostic or status text shown in the terminal

This does **not** apply to:
- Actual presentation content the system processes (slide text, extracted claims) —
  this is user *data*, not system *code*, and is expected to be Arabic, English, or
  mixed per section 11 (Multilingual Support).
- The `reason` field inside `ClaimVerification` when it quotes or references the
  original claim text — quoting the applicant's own words is not a violation of this
  rule, but the surrounding explanation text should still be English.

**Practical implication for manual testing:** when writing throwaway test/demo
scripts, avoid printing raw Arabic literals directly to the terminal for anything
that isn't genuinely testing Arabic-content handling. When Arabic input IS the
thing under test (e.g. normalize.py's Arabic character handling), that's fine and
expected — the constraint is about the *system's own* messages, not about refusing
to exercise Arabic-language features.






---

## 17. REVISED DECISION — embeddings: Gemini hosted instead of local Hugging Face

**Original plan:** `PROVIDER=hf` / `app/providers/hf_provider.py` running
`intfloat/multilingual-e5-large` locally via `sentence-transformers` (section 6).

**What actually happened:** the local model (~2.2GB), Windows symlink issues, and
an unreliable first-load made this impractical in the real dev environment.

**Revised choice:** `GeminiProvider.embed()` using `gemini-embedding-001` (GA as of
27 August 2026). `hf_provider.py` remains a future option; `embedding_model` /
`embedding_device` / `hf_*` settings are kept so a later switch-back is a config
change, not a rewrite.

**Accepted trade-offs:** embeddings now share Gemini free-tier data-use caveats
and consume from the same quota family as text generation. Privacy stance from
section 6 still applies: synthetic data in development; paid tier / Vertex before
real applicant data.

---

## 18. Final model choice + real-world free-tier restrictions discovered

After extensive live testing with a real Google Cloud account, several undocumented
free-tier behaviors were discovered:

1. New Google Cloud accounts are blocked from older/deprecated Gemini models
   (gemini-2.0-flash, gemini-2.5-flash-lite, etc.) with an explicit 404 error:
   "This model is no longer available to new users." This applies even though the
   same model works fine on established accounts.
2. The newest models (gemini-3.6-flash, gemini-3.7-flash) have a very tight
   free-tier daily quota (as low as 20 requests/day observed) shortly after launch,
   independent of account age.
3. The Google Search grounding tool has its own, separate, much stricter quota
   from plain text generation - confirmed via isolated testing: 4 consecutive plain
   generate_content calls succeeded with zero errors, while a single call with
   use_grounding=True failed immediately with 429 RESOURCE_EXHAUSTED on a brand
   new account. This is a distinct quota bucket, not the same one as text generation.

Final model choice: gemini-3.5-flash-lite - confirmed as both new-account-safe
(no 404) and having a usable free-tier quota for plain text generation.

Known open limitation: Track A (objective-claim fact-checking, which requires
use_grounding=True) is currently blocked by the grounding-tool-specific quota on
this account. This is NOT a code defect - evidence_general.py's existing design
correctly returns 'unclear' rather than fabricating a verdict when grounding is
unavailable. Resolving this requires enabling Billing on the Google Cloud project,
not a code change.

Verified working (real Gemini, gemini-3.5-flash-lite, no stub, no grounding needed
for Track B): A 2-slide presentation with a suspiciously-perfect performance claim
(99.9% accuracy) and a normal dataset-size claim (50,000 images) produced correct
claim extraction, correct hard-rule firing, real Gemini-generated contextual
reasoning, and hand-verified-correct scoring (fact_accuracy=55, overall=66).

---

## 19. REVISED DECISION — RPM pacing lives at the Gemini call site, not only in pipeline loops

**Symptom:** `POST /api/v1/presentation/analyze` intermittently returned
`DAILY_QUOTA_EXCEEDED` even on presentations with no objective/grounded claims,
and even when a single isolated `generate_content` call succeeded immediately
afterwards. Streamlit failed more often than `curl.exe` with the same file.

**Root cause (not guessed):** this account's free-tier **RPM** bucket is much
tighter than its daily generation quota. One `/analyze` fires several Gemini
calls back-to-back (one per non-empty slide for extraction, one per claim that
needs an LLM judgment, plus `generate_correction` for contradicted claims).
Pipeline-only `time.sleep` in `claim_extraction.py` / `fact_check.py`:

1. Does **not** cover `postprocess.generate_correction` (no sleep there).
2. Does **not** cover the **next HTTP request's first call** — Flask keeps one
   provider instance for the process, so two `/analyze` calls a few seconds
   apart (typical Streamlit retry, or curl then UI) share the same RPM window.
3. Used slide/claim **index** rather than "actual Gemini call count", so an
   empty leading slide could skip the "don't sleep before the first call" slot.

**Decision:**

- Keep `gemini_call_pacing_seconds` (default `3.0`) in `config/settings.py`.
- Keep in-loop sleeps in `claim_extraction.py` and `fact_check.py` (skip the
  first *actual* extraction call; skip the first claim in the verification
  loop) as an extra intra-request buffer.
- Add a **process-wide clock** in `app/providers/api_provider.py`
  (`wait_for_gemini_pacing`) used by both `complete()` and `embed()`. This is
  the authoritative gap between real Gemini round-trips, including corrections
  and the next request.
- On 429: log Google's `quotaValue` / `quotaMetric` / `retryDelay` (those
  fields are the ground truth for which bucket fired). If `retryDelay` is
  present and ≤ 60 seconds, retry **once** after that delay (RPM). Otherwise
  raise `DailyQuotaExceeded` (daily / grounding / unknown long wait). This
  revises the earlier "never retry 429" rule, which assumed every 429 was a
  daily cap.

Grounding-specific 429s remain claim-local in `evidence_general.py` (section 18).
Plain-generation 429s after the one RPM retry still abort the request.

---

## 20. Error-handling rule for `app/pipeline/` (from Bugs #1 and #4)

Any `except Exception` in `app/pipeline/*.py` must be preceded by
`except AppError: raise` (or a specific expected exception such as
`DailyQuotaExceeded: raise`). Do not re-wrap an already-meaningful error
inside a vaguer one (`FACT_CHECK_FAILED`, `CLAIM_EXTRACTION_FAILED`).

**Documented exception:** a `DailyQuotaExceeded` raised from a
`use_grounding=True` call in `evidence_general.py` is degraded to
`status="unclear"` with an explicit grounding-quota `reason` for **that
claim only**. It is not a systemic generation outage. Quota failures in
claim extraction and plausibility (no grounding) still propagate.

**Also:** an AI failure must not reuse the "nothing unusual found" reason
string. Track B provider failures return `status="unclear"` with a distinct
internal-error reason (Bug #1 was status-only; the reason text had the same
disguise).

---

---

## 21. Cross-Modal Integration Schema Finalized Against Demo AI's Contract

Following inspection of Demo AI's verified runtime output (transcription with timestamped segments `start`, `end`, `text`, `language`), Presentation AI's integration schema in `app/schemas/integration.py` is finalized.

> **CRITICAL ARCHITECTURAL NOTE**: This is **schema scaffolding only**. It is not wired into the live presentation pipeline (`app/pipeline/run.py`), not registered in API routes (`app/api/`), and not produced or consumed by any running execution flow today. The live presentation-only pipeline remains 100% offline and unaffected.

### A. Shared Taxonomy Sourcing
`SpokenClaim` reuses the exact same canonical taxonomy defined in `app/taxonomy/` and `app/schemas/presentation.py`:
- `claim_type`: Uses `ClaimType` enum (`performance`, `dataset`, `architecture`, `technology`, `algorithm`, `capability`, `business`).
- `property`: Canonical property names from `app/taxonomy/claim_taxonomy.yaml` (`accuracy`, `precision`, `recall`, `f1_score`, `latency`, `dataset_size`, `class_count`, `r2_score`).
- Qualitative spoken claims without numeric properties legitimately leave `subject`, `property`, `value`, `unit` as `None`.

### B. Finalized Models

#### 1. `SpokenClaim`
Represents one claim extracted from a demo video's transcript (produced by Demo AI's spoken claim extractor).
- `spoken_claim_id` (`str`): Identifier stable **ONLY within a single video analysis** (e.g. `"SPK-001"`). Same caveat as presentation `Claim.claim_id`.
- `text` (`str`, 1–5000 chars): Extracted spoken claim text, non-empty and bounded against untrusted input exhaustion.
- `start` (`float`, $\ge 0.0$): Start timestamp in seconds.
- `end` (`float`, $\ge \text{start}$): End timestamp in seconds, strictly validated $\ge \text{start}$.
- `source_segment_indices` (`list[int] | None`): Traceability back to Demo AI transcript segment indices.
- `claim_type` (`ClaimType | None`): Canonical claim type from shared taxonomy.
- `subject` (`str | None`), `property` (`str | None`), `value` (`float | str | None`), `unit` (`str | None`): Canonical quad.
- `language` (`str | None`): ISO language code reported by Demo AI.

#### 2. `ClaimAlignment`
Represents pairwise comparison between one presentation claim and one (or zero) matched spoken claim.
- `presentation_claim_id` (`str`): ID of presentation claim.
- `spoken_claim_id` (`str | None`): ID of spoken claim (`None` when relationship is `"missing"`).
- `relationship` (`Literal["consistent", "contradicted", "additional", "missing", "unrelated"]`):
  - `"consistent"`: Spoken claim corroborates presentation claim.
  - `"contradicted"`: Spoken claim conflicts with presentation claim.
  - `"additional"`: Spoken claim exists with no matching presentation claim (candidate said something new).
  - `"missing"`: Presentation claim exists with no matching spoken claim (never mentioned in demo).
  - `"unrelated"`: Claims are independent/unrelated in content.
- `confidence` (`float`, $0.0 \le c \le 1.0$): Match confidence score.
- `reason` (`NonEmptyStr`): Mandatory non-empty explanation (whitespace-only rejected).
- `evidence_quote` (`str | None`): Short quote from transcript supporting verdict.
- `timestamp_start` (`float | None`), `timestamp_end` (`float | None`): Video timestamps from matched spoken claim.

#### 3. `CrossModalSummary`
Aggregates alignment counts mirroring the Presentation `Summary` pattern:
- `total_alignments`: Total alignment pairs.
- `consistent`, `contradicted`, `additional`, `missing`, `unrelated`: Counts per relationship type.

#### 4. `CrossModalAnalysisResult`
The top-level result contract for future cross-modal consistency analysis:
- `schema_version` (`str`, default `"1.0.0"`): Present only at top-level contract.
- `status` (`Literal["completed", "partial", "failed"]`): Joint evaluation status.
- `presentation_analysis_id` (`str`): References `PresentationAnalysisResult.analysis_id`.
- `video_reference` (`str`): Filename or video identifier.
- `alignments` (`list[ClaimAlignment]`): Alignment list.
- `summary` (`CrossModalSummary`): Counts by relationship type.
- `overall_consistency_score` (`int`, 0–100): Deterministic aggregate score.

All integration models enforce `model_config = ConfigDict(extra="forbid")` to strictly reject unknown fields.

---

*Last updated: section 21 (cross-modal integration schema against Demo AI contract). Previous updates: section 19 (RPM pacing) and section 20 (error-handling rule).*


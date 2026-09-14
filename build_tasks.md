# Applicant Presentation AI — Build Tasks (Step by Step)

> هذا الملف مرجع تنفيذي كامل. امشِ عليه Task بعد Task، بالترتيب. كل Task فيه:
> **الهدف**، **الملفات المتأثرة**، **الكود/المنطق المطلوب بالتفصيل**، و**معيار الإنجاز (Definition of Done)**.
> استخدمه مباشرة مع أي AI (Claude، ChatGPT، إلخ) بإعطائه الـ Task نفسه كـ prompt.

---

## 0. التكنولوجيا المستخدمة (Tech Stack) — ثابتة، لا تتغير أثناء التنفيذ

| الطبقة | التقنية | السبب |
|---|---|---|
| Web Framework | **Flask** | تم اختياره صراحة بدل FastAPI |
| اللغة | **Python 3.12** | |
| التحقق من شكل البيانات (Schemas) | **Pydantic v2** | مستقل عن الـ framework، يستخدم في كل مكان |
| استخراج الـ PPTX | **python-pptx** | |
| الموديل الأساسي (LLM) | **Gemini Flash** عبر Google AI Studio (Free Tier) | مجاني، عنده Google Search grounding مدمجة |
| الـ Embeddings | **موديل مفتوح المصدر من Hugging Face يعمل محليًا** — `intfloat/multilingual-e5-large` عبر مكتبة `sentence-transformers` | مجاني بالكامل، بدون rate limit، يدعم عربي/إنجليزي، لا بيانات تغادر السيرفر |
| الـ Prompts | **Jinja2 templates**، versioned (`v1`, `v2`, ...) | |
| التوثيق التلقائي للاستدعاءات | Logging عادي (Python `logging`) | |
| الـ Testing | **pytest** | |
| الـ Containerization | Docker + docker-compose | |
| Production server | **gunicorn** (وليس `flask run`) | |

**قاعدة صارمة طول المشروع:** لا يوجد أي كود في `app/pipeline/` أو `app/api/` يستورد `google-genai` أو `sentence-transformers` مباشرة. كل الاتصال بالموديلات يمر حصريًا عبر `app/providers/` (شرح كامل في Task 4).

---

## 1. شرح الـ Structure الكامل (خريطة المشروع)

```text
presentation-ai/
│
├── app/
│   ├── main.py                    # نقطة تشغيل Flask (Application Factory)
│   ├── errors.py                  # كل الأخطاء المخصصة + معالجاتها
│   ├── telemetry.py               # تسجيل كل استدعاء AI (تكلفة، مدة، نجاح/فشل)
│   │
│   ├── api/                       # طبقة HTTP فقط — بدون أي منطق عمل بداخلها
│   │   ├── routes_health.py       # GET /healthz
│   │   └── routes_presentation.py # POST /api/v1/presentation/analyze
│   │
│   ├── pipeline/                  # كل خطوة من خطوات التحليل، كل واحدة في ملف منفصل
│   │   ├── run.py                 # الـ orchestrator — يربط كل الخطوات ببعض
│   │   ├── extract_pptx.py        # [Deterministic] استخراج نص/جداول من pptx
│   │   ├── normalize.py           # [Deterministic] تنظيف النص عربي/إنجليزي
│   │   ├── claim_extraction.py    # [AI] استخراج وتصنيف الـ claims
│   │   ├── evidence_general.py    # [AI] المسار الأول — تحقق بالبحث الخارجي
│   │   ├── plausibility.py        # [AI + Deterministic] المسار الثاني — فحص المعقولية
│   │   ├── fact_check.py          # موزّع يحدد أي claim يروح لأي مسار
│   │   ├── scoring.py             # [Deterministic] حساب السكور النهائي
│   │   └── postprocess.py         # [AI + Deterministic] التصحيحات + الخطورة + أسئلة المقابلة
│   │
│   ├── prompts/
│   │   ├── registry.py            # يحمّل ويشغّل قوالب الـ prompts
│   │   └── templates/             # ملفات .jinja، كل واحد بنسخة (v1, v2, ...)
│   │
│   ├── providers/                 # طبقة العزل عن أي موديل خارجي
│   │   ├── base.py                # العقد الموحّد (Interface) لكل الموديلات
│   │   ├── factory.py             # يبني الـ provider المناسب حسب الإعدادات
│   │   ├── api_provider.py        # تطبيق فعلي لـ Gemini
│   │   ├── hf_provider.py         # تطبيق الـ embeddings المحلية
│   │   ├── local_provider.py      # موديل محلي بديل (اختياري، للتطوير بدون إنترنت)
│   │   ├── stub_provider.py       # نسخة وهمية للاختبار، بدون أي اتصال إنترنت
│   │   └── embeddings.py          # طبقة cache فوق الـ embeddings
│   │
│   ├── schemas/
│   │   └── presentation.py        # شكل الـ Output الكامل (العقد الرسمي للـ API)
│   │
│   └── taxonomy/                  # قاموس موحّد لأسماء الـ claims (لأجل التكامل مع Demo AI لاحقًا)
│       ├── claim_taxonomy.yaml
│       └── canonicalize.py
│
├── config/
│   ├── settings.py                 # كل الإعدادات (متغيرات البيئة)
│   ├── providers.yaml
│   └── logging.yaml
│
├── docs/                           # التوثيق — يجب أن يبقى متزامنًا مع الكود الفعلي
│   ├── DECISIONS.md                # كل القرارات المعمارية (المرجع الأعلى)
│   ├── ARCHITECTURE.md
│   ├── PROMPTS.md
│   ├── PROVIDERS.md
│   └── RUNBOOK.md
│
├── eval/                           # قياس جودة الاستخراج والـ fact-checking
│   ├── datasets/presentation-extraction/v1/labels.jsonl
│   └── runners/run_extraction.py
│
├── tests/
│   ├── unit/                       # اختبارات لكل ملف لوحده، بدون AI حقيقي
│   └── integration/                # اختبار الـ pipeline كامل عبر الـ API
│
├── ui/streamlit_app.py             # أداة داخلية بسيطة لمعاينة النتائج أثناء التطوير فقط
│
├── .env.example                    # نموذج متغيرات البيئة
├── pyproject.toml                  # المكتبات المطلوبة
├── Dockerfile / docker-compose.yml
└── Makefile                        # أوامر مختصرة (install/run/test)
```

**القاعدة الذهبية للـ structure:** أي كود بيتعامل مع بيانات ثابتة أو حسابات (extraction, normalize, scoring) يروح في ملف واضح بينفّذ بدون AI. أي كود محتاج "فهم/حكم" (claim extraction, fact-check, plausibility) يمر عبر `app/providers/` وله prompt خاص بيه في `app/prompts/templates/`.

---

## 2. مبادئ التصميم الملزمة (خد بالك منها في كل Task)

هذه ليست تفاصيل تنفيذية، هذه قواعد يجب ألا يخالفها أي كود جديد:

1. **مسارين للـ claims، مش مسار واحد** (`app/schemas/presentation.py: ClaimTrack`):
   - `objective` (معلومات عامة/تقنية) → لازم تتحقق من مصدر خارجي حقيقي فقط.
   - `project_specific` (نتائج المتقدم الشخصية) → لا يوجد دليل خارجي، يُستخدم فحص معقولية فقط.
2. **حالات الـ Claim الست الثابتة** (لا تُضاف حالة جديدة بدون تحديث `docs/DECISIONS.md` أولًا):
   `supported | contradicted | project_unsupported | plausibility_flag | unclear | not_checkable`
3. **لا حكم `contradicted` بدون مصدر خارجي حقيقي مرفق.** لو الموديل رجّع `contradicted` من غير مصدر (grounding source)، الكود يفرض تخفيضها لـ `unclear` — هذا منطق برمجي إجباري في `evidence_general.py`، وليس مجرد تعليمة في الـ prompt.
4. **لا اختراع تصحيحات (corrections).** أي نص تصحيح لازم مبني على الدليل فعليًا، وإلا يُستخدم النص الاحتياطي الثابت: *"No verified value was found in the available evidence."*
5. **الإخراج JSON فقط.** لا واجهة، لا قرار نهائي Accept/Reject من النظام — القرار للـ HR دائمًا.
6. **الفصل بين Deterministic و AI** في كل ملف Pipeline (موضح في التعليق العلوي لكل ملف).

---

## Phase 0 — التجهيز (Task 0.1 – 0.3)

### Task 0.1 — تجهيز بيئة العمل ✅ DONE
> **ملاحظة من التنفيذ الفعلي:** ظهرت مشكلتين حقيقيتين وقت التنفيذ:
> 1. `pyproject.toml` كان محتاج `[tool.setuptools.packages.find] include = ["app*", "config*"]` صراحة، وإلا `pip install -e .` يفشل بخطأ "multiple top-level packages discovered" (لأن المشروع فيه أكتر من مجلد top-level: app, config, tests, eval, ui).
> 2. `sentence-transformers` (بيجيب معاه PyTorch) اتفصل لـ optional dependency group اسمها `embeddings` بدل ما يكون في التثبيت الأساسي — عشان نخليه يتركب بس وقت الحاجة الفعلية ليه (Task 2.3)، مش من الأول.

**الهدف:** بيئة Python جاهزة ومكتبات مثبّتة.
**الأوامر:**
```bash
cd presentation-ai
python3 -m venv .venv
source .venv/bin/activate         # أو .venv\Scripts\activate على ويندوز
pip install -e ".[dev]"
cp .env.example .env
```
**معيار الإنجاز:** الأمر `python -c "import flask, pydantic, pptx"` يعمل بدون أخطاء.

### Task 0.2 — التحقق من الإعدادات ✅ DONE
**الملفات:** `scripts/check_env.py`
**الهدف:** التأكد إن الإعدادات متوافقة قبل أي تشغيل.
**الأمر:** `python scripts/check_env.py`
**معيار الإنجاز:** الرسالة `Environment OK. provider=stub ...` تظهر (لأن `.env` بيبدأ بـ `PROVIDER=stub`).

### Task 0.3 — أول تشغيل (بدون AI حقيقي) ✅ DONE
**الأمر:** `make run` ثم في نافذة تانية:
```bash
curl http://localhost:8100/healthz
```
**معيار الإنجاز:** الرد `{"status": "ok"}`.

---

## Phase 1 — الأساس: Extraction + API + Scoring (بدون AI حقيقي)

> كل الـ Tasks هنا تُختبر بـ `PROVIDER=stub` في `.env`، حتى لا نحتاج مفتاح Gemini بعد.

### Task 1.1 — استخراج محتوى الـ PPTX ✅ DONE (مُختبر فعليًا بملف فيه جدول)
**الملف:** `app/pipeline/extract_pptx.py`
**Deterministic — لا AI.**
**المطلوب بالتفصيل:**
- دالة `extract(file_bytes: bytes) -> ExtractedPresentation`
- تستخدم `python-pptx`، تفتح الملف من `BytesIO`
- تمشي على كل `slide` وتاخد:
  - العنوان (`slide.shapes.title`)
  - كل `text_frame` نصوص عادية
  - كل `shape.has_table` → تحويل الصفوف لنص منظم (`" | "` بين الأعمدة)
- **لازم** كل عنصر يحمل `slide_number` بتاعه (رقم السلايد الحقيقي، يبدأ من 1)
- الصور تُتجاهل في هذه المرحلة (Phase 2 لاحقًا)

**اختبار يدوي:**
```python
from app.pipeline.extract_pptx import extract
result = extract(open("sample.pptx", "rb").read())
print(result.slide_count, result.slides[0].elements)
```
**معيار الإنجاز:** كل سلايد في ملف تجريبي بترجع بعدد العناصر الصحيح ورقم السلايد الصحيح، والجداول بتترجم لنص مقروء.

---

### Task 1.2 — تنظيف وتطبيع النص (Normalization) ✅ DONE (مختبر على جهاز المستخدم فعليًا)
> **ملاحظة من التنفيذ الفعلي:** كانت خريطة تطبيع الحروف العربية بتحول كل حرف لنفسه بالظبط (نفس الـ Unicode code point) — يعني كانت بلا أي تأثير خالص. اتصلحت لتطبّع فعليًا حروف مختلفة الـ encoding بصريًا متطابقة (زي الياء الفارسية `ی` مقابل الياء العربية `ي`، والكاف الفارسية `ک` مقابل الكاف العربية `ك`)، مع تجنّب لمس الهمزات (أ/إ/آ) والتاء المربوطة/الهاء لأنها بتغيّر المعنى فعليًا.

**الملف:** `app/pipeline/normalize.py`
**Deterministic — لا AI.**
**المطلوب بالتفصيل:**
- دالة `normalize(extracted) -> ExtractedPresentation`:
  - إزالة التكرار (نفس النص مرتين في نفس السلايد)
  - إزالة العناصر الفارغة
  - تنظيف المسافات الزائدة (`\s+` → مسافة واحدة)
  - تطبيع Unicode (`unicodedata.normalize("NFKC", text)`) لتوحيد أشكال الحروف العربية المختلفة
  - **ممنوع** حذف أي أرقام أو وحدات أو كلمات نفي — دي بتغيّر معنى الـ claim
- دالة `slide_to_prompt_text(slide) -> str`: تحويل السلايد لنص واحد جاهز يُرسل للـ prompt، بصيغة:
  ```
  [Title] ...
  [Text] ...
  [Table] ...
  ```

**معيار الإنجاز:** تجربة سلايد فيه نفس الجملة مكررة مرتين → يرجع مرة واحدة بس. سلايد بعربي ممزوج بإنجليزي → يفضل مقروء وسليم.

---

### Task 1.3 — تعريف شكل الـ Output (Schema) — **أهم Task في المشروع** ✅ DONE
> **ملاحظة من التنفيذ الفعلي:** قاعدة "reason إجباري وغير فارغ" كانت موجودة كـ `description` (توثيق) بس، مش كقيد فعلي — يعني `reason=""` كان بيعدي عادي من غير أي رفض. اتصلحت بإضافة `NonEmptyStr` (نوع Pydantic مخصص بـ `strip_whitespace=True, min_length=1`) بيرفض أي نص فاضي أو كله مسافات فعليًا وقت التشغيل.

**الملف:** `app/schemas/presentation.py`
**المطلوب بالتفصيل (Pydantic models):**

```text
ClaimType     = performance | dataset | architecture | technology | algorithm | capability | business
ClaimTrack    = objective | project_specific
Importance    = high | medium | low
ClaimStatus   = supported | contradicted | project_unsupported | plausibility_flag | unclear | not_checkable
Severity      = critical | high | medium | low

Claim: claim_id, slide_number, text, claim_type, track, importance,
       subject, property, value, unit   (آخر 4 اختياريين، للتطبيع)

Evidence: source_type, source_url, snippet

ClaimVerification: claim_id, status, confidence (0-1), reason (إجباري، غير فارغ أبدًا),
                    evidence: list[Evidence]

Correction: claim_id, text
Issue: slide_number, claim_id, severity, status, claim_text, correction
Scores: overall, fact_accuracy, evidence_coverage, claim_reliability  (كل واحدة 0-100)
Summary: total_claims + عداد لكل status
InterviewQuestion: slide_number, claim_id, suggested_question

PresentationAnalysisResult:  # الجسم الكامل لرد الـ API
   analysis_id, status, presentation (filename + slide_count),
   scores, summary, claims, verifications, issues, suggested_interview_questions
```

**قاعدة حرجة:** `ClaimVerification.reason` **إجباري وغير فارغ أبدًا** — ممنوع أي status يرجع بدون تفسير مكتوب، خصوصًا `plausibility_flag`.

**معيار الإنجاز:** بناء `PresentationAnalysisResult` بأقل بيانات ممكنة وعمل `.model_dump()` عليه يرجع JSON صحيح بدون أخطاء Validation.

---

### Task 1.4 — قاموس تطبيع الـ Claims (Taxonomy) ✅ DONE (مختبر على جهاز المستخدم فعليًا)
**الملفات:** `app/taxonomy/claim_taxonomy.yaml`, `app/taxonomy/canonicalize.py`
**Deterministic — لا AI.**
**المطلوب بالتفصيل:**
- ملف YAML فيه:
  - قائمة `claim_types` الثابتة (مطابقة لـ `ClaimType` في الـ schema)
  - قائمة `properties` (accuracy, precision, recall, f1_score, latency, dataset_size, class_count, r2_score) وكل واحدة عندها `aliases` (بالعربي والإنجليزي) + `unit`
- دالة `canonicalize_property(raw: str) -> str`: تحوّل أي alias لاسمه الموحّد. لو مش لاقي، ترجع النص الأصلي زي ما هو (مش تخترع تخمين).
- دالة `is_known_claim_type(claim_type: str) -> bool`

**معيار الإنجاز:** `canonicalize_property("Accuracy Rate")` و`canonicalize_property("acc")` و`canonicalize_property("دقة")` كلهم يرجعوا `"accuracy"`.

---

### Task 1.5 — الإعدادات (Settings) ✅ DONE (مختبر على جهاز المستخدم فعليًا)
**الملف:** `config/settings.py`
**المطلوب:** كلاس `Settings` (Pydantic `BaseSettings`) بيقرأ من `.env`، فيه:
- `provider` (api/hf/local/stub)
- `gemini_api_key`, `gemini_model`
- `embedding_model`, `embedding_device`
- `feature_image_analysis`, `feature_web_grounding`
- `daily_request_cap`, `claim_batch_size`
- `api_port`, `log_level`
- دالة مساعدة `get_settings()` بـ `@lru_cache` (نسخة واحدة فقط طول عمر التطبيق)

**معيار الإنجاز:** تغيير `PROVIDER` في `.env` وإعادة تشغيل السيرفر يغيّر سلوكه فعليًا (تأكيد بصري في اللوج عند بدء التشغيل).

---

### Task 1.6 — عقد الـ Provider (الأساس لكل تكامل AI لاحق) ✅ DONE (مختبر على جهاز المستخدم فعليًا)
**الملف:** `app/providers/base.py`
**المطلوب بالتفصيل:**
- كلاس `CompletionResult`: `text`, `model_version`, `tokens_in`, `tokens_out`, `grounding_sources: list[dict]`
- كلاس مجرّد (ABC) `ProviderAdapter` بدالتين إجباريتين:
  - `complete(prompt, response_schema=None, use_grounding=False, temperature=0.2) -> CompletionResult`
  - `embed(texts: list[str]) -> list[list[float]]`

**لماذا هذا مهم:** أي كود في `pipeline/` يتعامل مع هذا العقد فقط، لا يعرف Gemini أو أي مكتبة تانية. هذا يسمح باستبدال الموديل لاحقًا بدون تعديل منطق الـ pipeline.

**معيار الإنجاز:** أي كلاس جديد يرث من `ProviderAdapter` ولازم ينفّذ الدالتين وإلا Python هيرفض إنشاء نسخة منه.

---

### Task 1.7 — الـ Stub Provider (وهمي، للاختبار بدون إنترنت) ✅ DONE (مختبر على جهاز المستخدم فعليًا — 7/7 tests passed)
**الملف:** `app/providers/stub_provider.py`
**المطلوب بالتفصيل:**
- `complete()` يرجع ردود مختلفة **حسب نوع الاستدعاء** (لأن كل مرحلة محتاجة شكل مختلف):
  - لو `response_schema` من نوع array → رجّع claim وهمي واحد بصيغة JSON صحيحة
  - لو النص فيه كلمة `"flagged"` (يعني ده استدعاء plausibility) → رجّع `{"flagged": true, "reason": "...", "confidence": 0.6}`
  - لو النص فيه `"status"` (يعني fact_check) → رجّع `{"status": "unclear", "confidence": 0.0, "reason": "..."}`
  - لو النص فيه `"neutral sentence"` (يعني correction) → رجّع نص عادي مش JSON
- لو `use_grounding=True` → رجّع `grounding_sources` وهمية، وإلا قائمة فاضية
- `embed()` يرجع vectors ثابتة الطول (زي `[0.0]*8`) لكل نص

**⚠️ ملاحظة من تجربة فعلية:** هذا التمييز حسب محتوى الـ prompt **ضروري**، لأن نفس دالة `complete()` بتُستدعى من 4 أماكن مختلفة بأشكال ردود مختلفة تمامًا. تجاهل هذه النقطة هيسبب `AttributeError` وقت تشغيل الـ pipeline كامل (حصل فعليًا أثناء بناء هذا المشروع).

**معيار الإنجاز:** استدعاء `provider.complete()` بأنواع الطلبات الأربعة المختلفة يرجع شكل صحيح لكل نوع.

---

### Task 1.8 — الـ Factory ✅ DONE (مختبر على جهاز المستخدم فعليًا)
**الملف:** `app/providers/factory.py`
**المطلوب:** دالة `build_provider(settings) -> ProviderAdapter` بتقرأ `settings.provider` وتستورد وترجع الكلاس المناسب (`GeminiProvider` / `HFProvider` / `LocalProvider` / `StubProvider`) — الاستيراد يكون **داخل** كل شرط (Lazy import) عشان الموديل اللي مش مستخدم متتحملش مكتبته أصلًا.

**معيار الإنجاز:** تغيير `PROVIDER=stub` لـ `PROVIDER=api` بدون مفتاح API يرمي `RuntimeError` واضح، مش يفشل بصمت.

---

## ⚠️ تعديل على الترتيب (اكتُشف أثناء التنفيذ الفعلي)

`app/main.py` (Task 1.9) يستورد `routes_presentation.py` الذي يستورد `pipeline/run.py` الذي
بدوره يستورد `claim_extraction.py`, `fact_check.py`, `evidence_general.py`, `plausibility.py`.
هذه الملفات **لا تحتاج فعليًا اتصال Gemini حقيقي لتعمل** — هي تتعامل مع `ProviderAdapter`
كـ abstraction فقط، ويكفيها `stub_provider` تمامًا. لذلك تم نقل بناءها إلى **قبل** Task 1.9
بدل تركها لـ Phase 2 كما في الترتيب الأصلي، حتى يعمل معيار إنجاز Task 1.9 فعليًا (تشغيل
السيرفر بدون أخطاء). Phase 2 أصبحت تركّز فقط على: كتابة نص الـ prompts النهائي، وتوصيل
Gemini الحقيقي (`api_provider.py`)، والـ embeddings (`hf_provider.py`) — بدون تغيير في
منطق التوزيع بين المسارين نفسه.

تمت إضافة Task 1.9a (Prompts Registry)، Task 1.9b (Claim Extraction)، Task 1.9c
(Evidence General + Plausibility + Fact Check Dispatcher) قبل استكمال Task 1.9.

### Task 1.9 — Flask App (Application Factory)


**الملف:** `app/main.py`
**المطلوب بالتفصيل:**
- دالة `create_app() -> Flask` (مش `app = Flask(...)` مباشر — عشان الاختبارات تقدر تعمل نسخ منفصلة)
- بتحمّل `Settings`، وتبني الـ `provider` والـ `prompts registry` **مرة واحدة عند بدء التشغيل** وتخزنهم في `app.extensions`
- تسجّل الـ Blueprints (`routes_health`, `routes_presentation`)
- تسجّل معالجات الأخطاء

**معيار الإنجاز:** `flask --app app.main:create_app run` يشتغل بدون Exception، واللوج بيوضح `provider=stub` عند البدء.

---

### Task 1.10 — الأخطاء الموحدة (Error Handling)
**الملف:** `app/errors.py`
**المطلوب:** كلاسات Exception لكل كود خطأ من القائمة دي (مطابقة تمامًا لأكواد الخطأ في المستند الأصلي):
```text
INVALID_FILE, UNSUPPORTED_FORMAT, FILE_TOO_LARGE, CORRUPTED_FILE,
EXTRACTION_FAILED, CLAIM_EXTRACTION_FAILED, FACT_CHECK_FAILED, SCORING_FAILED, INTERNAL_ERROR
```
كل كلاس عنده `code` و`status` (HTTP status code)، ودالة `register_error_handlers(app)` بتحوّل أي استثناء لرد JSON موحد الشكل:
```json
{"status": "error", "error": {"code": "...", "message": "..."}}
```

**معيار الإنجاز:** رفع ملف بامتداد غلط يرجع `400` مع `code: INVALID_FILE`.

---

### Task 1.11 — الـ Route الرئيسي
**الملف:** `app/api/routes_presentation.py`
**المطلوب:**
- `POST /api/v1/presentation/analyze`
- يقبل `multipart/form-data` بحقل اسمه `file` فقط (بالإضافة لـ `applicant_id`/`job_id` اختياريين وغير مؤثرين على المنطق)
- يتحقق الامتداد `.pptx`، وإلا `InvalidFile`
- يستدعي `run_presentation_analysis(...)` من `app/pipeline/run.py`
- يرجع `result.model_dump()` كـ JSON

**معيار الإنجاز:**
```bash
curl -X POST http://localhost:8100/api/v1/presentation/analyze -F "file=@sample.pptx"
```
يرجع `200` وJSON كامل الشكل (حتى لو البيانات وهمية من الـ stub).

---

### Task 1.12 — حساب السكور
**الملف:** `app/pipeline/scoring.py`
**Deterministic — لا AI.**
**المطلوب بالتفصيل:**
- وزن الأهمية: `high=3, medium=2, low=1`
- درجة كل status: `supported=1.00, contradicted=0.00, project_unsupported=0.50, plausibility_flag=0.60, unclear=0.50, not_checkable=مُستبعد تمامًا`
- `fact_accuracy = 100 × (مجموع الدرجات المرجّحة ÷ مجموع الأوزان)`
- `evidence_coverage`: نسبة الـ claims اللي وصلت لحكم له أساس (دليل حقيقي أو حكم معقولية صريح) من إجمالي الأوزان
- `overall = 0.50×fact_accuracy + 0.25×evidence_coverage + 0.25×claim_reliability`
- **لازم تكون الدالة pure function** بدون أي استدعاء provider — نفس المدخلات = نفس المخرجات دايمًا

**معيار الإنجاز:** كل الـ claims بحالة `supported` → `fact_accuracy = 100`. Claim مهم (`high`) بحالة `contradicted` يأثر على السكور أكتر من Claim بحالة `contradicted` لكن أهميته `low`.

---

### Task 1.13 — بناء الـ Issues وأسئلة المقابلة (الجزء الديترمنستيك فقط)
**الملف:** `app/pipeline/postprocess.py` (جزء `build_issues` و`build_interview_questions` و`assign_severity`)
**Deterministic لهذا الجزء تحديدًا.**
**المطلوب:**
- `assign_severity(claim, verification)`: جدول تحويل ثابت (status, importance) → severity، مثلًا `(contradicted, high) → critical`
- `build_issues(...)`: لكل verification عندها severity (يعني تستحق الظهور كمشكلة)، ابنِ `Issue` وربطها بالـ correction لو موجود
- `build_interview_questions(...)`: **فقط** من الـ verifications بحالة `plausibility_flag`، وابنِ سؤال بصيغة: *"Can you walk me through how you arrived at: '...'? (السبب)"*

**معيار الإنجاز:** Claim بحالة `plausibility_flag` يظهر في `suggested_interview_questions`، وClaim بحالة `supported` لا يظهر في `issues` أصلًا.

---

### Task 1.14 — ربط كل حاجة (Orchestrator)
**الملف:** `app/pipeline/run.py`
**المطلوب:** دالة `run_presentation_analysis(filename, content, provider, prompts, settings, applicant_id=None, job_id=None) -> PresentationAnalysisResult` تنفّذ بالترتيب:
```text
extract_pptx.extract → normalize.normalize → claim_extraction.extract_claims
→ fact_check.verify_claims → scoring.compute_scores
→ postprocess (corrections + issues + interview questions)
→ تجميع PresentationAnalysisResult النهائي
```
مع `try/except` مناسب حول كل مرحلة يرمي الخطأ الصحيح من `app/errors.py`.

**معيار الإنجاز — نهاية Phase 1 بالكامل:**
```bash
make run   # مع PROVIDER=stub
curl -X POST .../analyze -F "file=@sample.pptx"
```
يرجع JSON **كامل الشكل والحقول** (حتى لو المحتوى من الـ stub) + كل الـ unit tests في `tests/unit/` بتعدي.

---

## Phase 2 — دمج AI حقيقي (Gemini)

> من هنا فصاعدًا نحتاج مفتاح Gemini API مجاني من https://aistudio.google.com، ويوضع في `.env` تحت `GEMINI_API_KEY`، مع تغيير `PROVIDER=api`.

### Task 2.1 — كتابة الـ Prompts
**الملفات:** `app/prompts/templates/*.jinja`
**المطلوب لكل ملف (4 ملفات):**

1. **`claim_extract.v1.jinja`** — يستخرج claims من نص سلايد واحد، يرجع JSON array، كل claim معلّم بـ `track` (objective/project_specific).
2. **`fact_check.v1.jinja`** — **يجب** أن يوجّه الموديل لاستخدام أداة البحث (grounding)، يرجع `{status, confidence, reason}`، وتعليمة صريحة: *"لو مفيش مصدر واضح، رجّع unclear، ماتخمنش."*
3. **`plausibility_judgment.v1.jinja`** — يرجع `{flagged, reason, confidence}`، مع تعليمة: *"هذا فحص معقولية وليس فحص صحة — لا يوجد دليل خارجي، احكم على أساس النطاقات المعتادة لنوع المهمة."*
4. **`correction_generate.v1.jinja`** — يرجع **نص عادي** (مش JSON)، مبني حصريًا على الدليل المُعطى، مع نص احتياطي ثابت لو مفيش قيمة واضحة.

**معيار الإنجاز:** تشغيل كل prompt يدويًا (مباشرة، بدون باقي الـ pipeline) وعينة نص، والتأكد إن الرد بيطابق الشكل المطلوب.

---

### Task 2.2 — الاتصال الفعلي بـ Gemini
**الملف:** `app/providers/api_provider.py`
**المطلوب بالتفصيل:**
```python
from google import genai

self._client = genai.Client(api_key=settings.gemini_api_key)

# داخل complete():
tools = [{"google_search": {}}] if use_grounding else None
response = self._client.models.generate_content(
    model=self._settings.gemini_model,
    contents=prompt,
    config={"temperature": temperature, "tools": tools},
)
```
- استخراج `grounding_sources` من الـ response (لو الموديل استخدم أداة البحث فعليًا) — **لو مفيش مصادر رجعت من الأداة، رجّع قائمة فاضية، لا تخترع مصدر.**
- التعامل مع أخطاء الشبكة/الـ rate limit (`429`) برمي `DailyQuotaExceeded` من `app/errors.py`

**معيار الإنجاز:**
```bash
# .env: PROVIDER=api, GEMINI_API_KEY=...
make run
curl -X POST .../analyze -F "file=@sample.pptx"
```
يرجع claims حقيقية مستخرجة فعليًا من محتوى الملف، مش بيانات وهمية.

---

### Task 2.3 — تفعيل embeddings محلية
**الملف:** `app/providers/hf_provider.py`
**المطلوب:**
```python
from sentence_transformers import SentenceTransformer
# تحميل كسول (lazy) عبر @cached_property — التحميل مرة واحدة فقط لكل عملية تشغيل
self._model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device)
```
`embed()` يستخدم `self._model.encode(texts, normalize_embeddings=True).tolist()`

**معيار الإنجاز:** أول استدعاء بياخد وقت (تحميل الموديل)، الاستدعاءات اللي بعده سريعة (الموديل محمّل في الذاكرة).

---

### Task 2.4 — تفعيل المسار الأول (Objective Claims)
**الملف:** `app/pipeline/evidence_general.py`
**المطلوب بالتفصيل — القاعدة الحرجة هنا:**
```python
MIN_CONFIDENCE_FOR_VERDICT = 0.75

if status in ("supported", "contradicted"):
    if not result.grounding_sources or confidence < MIN_CONFIDENCE_FOR_VERDICT:
        status = "unclear"   # ⚠️ إجباري، حتى لو الموديل قال غير ذلك
```
هذا **الضمان البرمجي** إن أي حكم قاطع لازم مبني على مصدر حقيقي وثقة كافية.

**معيار الإنجاز:** عمل تجربة بـ claim عام صحيح 100% (زي "Python is an interpreted language") → `supported` مع `source_url` حقيقي. وclaim عام غلط واضح → `contradicted` مع مصدر حقيقي.

---

### Task 2.5 — تفعيل المسار الثاني (Project-Specific Claims)
**الملف:** `app/pipeline/plausibility.py`
**المطلوب بالتفصيل:**
- `hard_rules(claim)`: قواعد بدون AI — قيم مثل `100%`, `99.9%`, أو أي metric ≥ `99.5%` → flag تلقائي؛ claim بدون أي سياق (لا subject ولا property) → flag تلقائي
- `contextual_judgment(...)`: يُستدعى فقط لو الـ hard rules ما لقتش حاجة، يستخدم الـ prompt رقم 3، **يرجع دائمًا `reason` غير فارغ**

**معيار الإنجاز:** claim زي "الموديل حقق 100% دقة" → `plausibility_flag` من الـ hard rules مباشرة (بدون استدعاء AI حتى). claim زي "الموديل حقق 87% دقة على dataset من 50000 صورة" → `project_unsupported` عادي بدون flag.

---

### Task 2.6 — تفعيل توليد التصحيحات
**الملف:** `app/pipeline/postprocess.py` (دالة `generate_correction`)
**المطلوب:** تُستدعى **فقط** لو `status == "contradicted"` **و** فيه evidence مرفق. النص الناتج يُبنى حصريًا من `evidence.snippet` — ممنوع أي معلومة زيادة عن كده.

**معيار الإنجاز:** claim متناقض مع دليل واضح → تصحيح نصي دقيق ومحدد. claim متناقض بدون دليل كافٍ (نادر بسبب Task 2.4) → النص الاحتياطي الثابت.

---

## Phase 3 — الاختبار والتقييم

### Task 3.1 — اختبارات الوحدة (موجودة، وسّعها)
**الملفات:** `tests/unit/*.py`
لكل ملف جديد كتبته في Phase 1 أو 2، أضف اختبار يغطي:
- حالة النجاح العادية
- حالة حافة (input فاضي، قيمة غريبة)
- (للـ AI فقط) اختبار عبر `stub_provider`، لا يوجد اتصال إنترنت حقيقي في `tests/`

### Task 3.2 — بناء Dataset تقييم حقيقي
**الملف:** `eval/datasets/presentation-extraction/v1/labels.jsonl`
اجمع 10-15 presentation متنوعة (عربي/إنجليزي/مختلط)، وحط توقعاتك اليدوية لكل claim (النص، الـ track، الحالة المتوقعة).

### Task 3.3 — تشغيل التقييم
**الملف:** `eval/runners/run_extraction.py`
نفّذ الجزء المطلوب (موجود TODO فيه): شغّل الـ pipeline على كل presentation في الـ dataset، قارن بالـ labels اليدوية، احسب Precision/Recall/F1.

**معيار الإنجاز:** تقرير أرقام واضح يوضح مين أضعف نقطة (extraction، fact-check، أو plausibility) عشان تعرف تحسن الـ prompt المناسب.

---

## Phase 4 — التلميع النهائي

### Task 4.1 — مراجعة الأمان
راجع القائمة دي على الكود الفعلي (مش نظريًا):
- حد أقصى لحجم الملف (`MAX_CONTENT_LENGTH` في `app/main.py`) ✓ موجود بالفعل (25MB)
- لا يوجد أي `eval()` أو تنفيذ محتوى من داخل الملف المرفوع
- `app/telemetry.py` لا يسجّل نص السلايدات الخام، فقط عدادات وأرقام

### Task 4.2 — مزامنة التوثيق مع الكود الفعلي
راجع `docs/ARCHITECTURE.md` و`docs/PROVIDERS.md` و`docs/PROMPTS.md` وتأكد إنها بتوصف الكود الحالي فعليًا، مش الخطة النظرية بس.

### Task 4.3 — اختبار الحالات الحرجة (Edge Cases)
- ملف `.pptx` تالف → `CorruptedFile` برد `400` واضح
- presentation بدون أي slide → `ExtractionFailed`
- presentation بدون أي claim قابل للتحقق (كله عناوين) → رد ناجح بـ `total_claims: 0`
- تجاوز حد Gemini اليومي → `DailyQuotaExceeded` برد `429` واضح، مش انهيار للسيرفر

---

## ملخص سريع: أي Task تفتح مع أي AI في كل مرة

لما تفتح محادثة جديدة مع أي AI لتنفيذ Task معين، ابعتله:
1. اسم الـ Task ورقمه من هذا الملف (مثال: "Task 2.4")
2. محتوى `docs/DECISIONS.md` (القرارات الملزمة)
3. الملف الحالي (لو موجود بالفعل) عشان يعدّل عليه مش يكتب من الصفر

بهذا الترتيب، أي AI هيقدر يكمل بالظبط من حيث ما وصلت، بدون ما يكرر شغل أو يخالف قرار سبق واتفقنا عليه.

---

## سجل الإنجاز الفعلي (Session Log مدمج) — محدّث حتى نهاية مراجعة Task 2.5

### Phase 1 — باقي التاسكات، أُنجزت من قِبل المستخدم منفردًا (موثقة في SESSION_LOG.md الخاص به)
- [x] Task 1.9a (إضافة غير مخططة) — `app/prompts/registry.py` + 4 ملفات `.jinja`
- [x] Task 1.9 — `app/main.py` ✅ DONE
- [x] Task 1.10 — `app/errors.py` ✅ DONE
- [x] Task 1.11 — `app/api/routes_presentation.py` ✅ DONE
- [x] Task 1.12 — `app/pipeline/scoring.py` ✅ DONE
- [x] Task 1.13 — `app/pipeline/postprocess.py` (الجزء الديترمنستيك) ✅ DONE
- [x] Task 1.14 — `app/pipeline/run.py` (orchestrator) ✅ DONE
  - **Bug found & fixed:** كان بيمسك `PackageNotFoundError` بس، فملف `.pptx` فاسد كان بيرجع
    `EXTRACTION_FAILED` بدل `CORRUPTED_FILE`. الحل: `except (PackageNotFoundError, zipfile.BadZipFile)`.
    تم التحقق برفع ملف `.txt` باسم `fake.pptx` فعليًا وتأكيد تغيّر الرد.

### Phase 2 — تقدم فعلي (أبعد من الخطة الأصلية، لكن موثّق كانحراف مفصح عنه)
- [x] Task 2.1 — مراجعة وإعادة كتابة الـ 4 prompts (صياغة أقوى، أمثلة صريحة، ربط مباشر بقواعد DECISIONS.md) ✅ DONE
- [x] Task 2.2 — `app/providers/api_provider.py` (Gemini حقيقي) ✅ DONE
  - **Bug found & fixed أثناء المراجعة الذاتية:** `DailyQuotaExceeded` كانت معرّفة محليًا جوه
    `api_provider.py` بدل `app/errors.py` المركزي — تم نقلها.
  - **مشكلة بيئة (مش كود):** اسم الموديل `gemini-2.5-flash` القديم اتلغى من جوجل (404) —
    اتغيّر لـ `gemini-flash-latest` في `config/settings.py` (alias دايم التحديث، بدل اسم إصدار ثابت).
  - **تحسين استقرار:** أُضيف retry logic (محاولتين إضافيتين + backoff) لأخطاء 503
    (`ServerError`) المؤقتة من جوجل، مع ترك أخطاء 429 (`ClientError`/quota) بدون retry
    لأن الانتظار مش هيحلها.
- [x] Task 2.4 — `app/pipeline/evidence_general.py` (Track A النهائي) — تمت المراجعة، **سليم من أول مرة** ✅ DONE
- [x] Task 2.5 — `app/pipeline/plausibility.py` (Track B النهائي) — تمت المراجعة، **لُقي وأُصلح bug حرج** ✅ DONE
  - **🐛 Bug حرج (اكتُشف بالمراجعة اليدوية، ثم تم التحقق آليًا):** عند فشل استدعاء الـ AI في
    `_contextual_judgment`، الكود القديم كان بيرجّع `status="project_unsupported"` (كأن الفحص
    تم بنجاح ولم يجد شيئًا غريبًا) بدل الإفصاح عن الفشل. هذا كان (أ) يخفي فشل النظام عن HR،
    و(ب) يرفع `evidence_coverage` score زورًا لأن `scoring.py:_has_basis()` يعتبر
    `project_unsupported` "له أساس". **الإصلاح:** عند الفشل، يرجع الآن `status="unclear"` —
    بما يطابق سلوك `evidence_general.py` في نفس الموقف تمامًا.
    **تم التحقق فعليًا:** اختبار بـ `MagicMock` provider يفشل عمدًا، تأكيد `status == "unclear"`. PASS ✅
  - **فجوة منطقية ثانوية (اكتُشفت واتصلحت بنفس المراجعة):** الـ hard rule كانت مقيدة بـ
    `claim.unit == "%"` فقط، فـ `f1_score`/`r2_score` (نطاقهم 0-1 بلا وحدة `%`) كانوا مستبعدين
    عمليًا من القاعدة الصلبة رغم وجودهم في `_FLAGGED_METRICS`. تم فصل المنطق لنطاقين
    (percentage-scale و0-1 scale). **تم التحقق فعليًا:** `f1_score=0.998` → flag صحيح. PASS ✅

### ملاحظات توثيق مفتوحة (منخفضة الأولوية — لم تُصلح بعد، فقط مُسجّلة)
- [ ] كود الخطأ النهائي هو `DAILY_QUOTA_EXCEEDED` (وليس `PROVIDER_QUOTA_EXCEEDED` كما في
      المسودة الأولى) — يحتاج توحيد أي توثيق قديم يذكر الاسم الأصلي.
- [ ] `config/logging.yaml` غير مُستخدم فعليًا حاليًا (`main.py` يستخدم `logging.basicConfig`
      مباشرة) — يحتاج توضيح في `docs/RUNBOOK.md` أو حذف الملف لتفادي اللبس.
- [ ] `response_schema` في `api_provider.py` لا يُمرَّر كـ JSON Schema حقيقي لـ Gemini API؛
      يُستخدم داخليًا فقط كـ flag لتفعيل `response_mime_type="application/json"` (بسبب تعارض
      حقيقي بين `tools` و`response_schema` في نفس الاستدعاء على الأرجح) — يحتاج تعليق/توثيق
      صريح في الكود أو `docs/PROVIDERS.md` حتى لا يُعتبر هذا خطأ لاحقًا ويُعاد "إصلاحه" بالغلط.

**الحالة الحالية:** Phase 0 وPhase 1 مكتملتان بالكامل ومُختبرتان فعليًا. Phase 2: تم إنجاز
Tasks 2.1, 2.2, 2.4, 2.5 (بترتيب مختلف عن الترتيب الأصلي في الخطة، لأن 2.4/2.5 لم تكن فعليًا
بحاجة لانتظار 2.3). **المتبقي في Phase 2:** Task 2.3 (`hf_provider.py` — embeddings محلية،
لم يبدأ بعد) وTask 2.6 (التحقق النهائي من `generate_correction` ضد claim متناقض حقيقي فعليًا
عبر Gemini حي، البنية جاهزة في `postprocess.py` لكن لم يُختبر end-to-end بعد).

---

## مراجعة عميقة لـ Task 2.4/2.5/2.6 — 4 bugs حقيقية اكتُشفت وأُصلحت (جلسة منفصلة)

هذه المراجعة تمت بعد رفع محتوى الملفات الفعلي للمراجعة اليدوية الكاملة (وليس فقط "الكود يعمل ظاهريًا").
**كل الإصلاحات التالية تم التحقق منها فعليًا عبر اختبارات محلية (بدون استهلاك أي Gemini quota)
بالإضافة إلى اختبار حي واحد ناجح على الأقل لكل حالة.**

### Bug #1 (حرج) — `plausibility.py`: فشل الـ AI كان يُقنَّع كـ "لا يوجد قلق"
عند فشل استدعاء الموديل في `_contextual_judgment`، الكود القديم كان يرجع
`status="project_unsupported"` (كأن الفحص تم بنجاح ولم يجد شيئًا) بدلاً من الإفصاح عن الفشل.
هذا كان (أ) يخفي فشل النظام عن HR، و(ب) يرفع `evidence_coverage` score زورًا لأن
`scoring.py:_has_basis()` يعتبر `project_unsupported` "له أساس".
**الإصلاح:** عند الفشل، يرجع الآن `status="unclear"`.
**تحقق فعلي:** اختبار بـ `MagicMock` provider يفشل عمدًا → `status == "unclear"`. PASS.

### Bug #2 (متوسط) — `plausibility.py`: الـ hard rule الخاصة بـ f1_score/r2_score معطّلة فعليًا
الشرط `claim.unit == "%"` يمنع القاعدة الصلبة من العمل أبدًا على `f1_score`/`r2_score`
(نطاقهما 0-1 بلا وحدة `%` حسب `claim_taxonomy.yaml`).
**الإصلاح:** فصل المنطق لنطاقين (percentage-scale و0-1 scale).
**تحقق فعلي:** `f1_score=0.998, unit=None` → flag صحيح مع سبب واضح. PASS.

### Bug #3 (حرج، اكتُشف بعد الاختبار الحي) — `plausibility.py`: قاعدة "بدون سياق" واسعة جدًا
القاعدة `if claim.subject is None and claim.property is None` كانت تُشعل flag تلقائي على
**أي** claim نوعي (architecture/technology/algorithm/capability/business) رغم أن هذه الأنواع
طبيعي جدًا ألا تحمل subject/property (هذه الحقول مخصصة للـ claims الرقمية). النتيجة: claim
بريئة تمامًا مثل "We used PostgreSQL as our primary database" كانت تُصنَّف `plausibility_flag`
دائمًا — كان هذا سيُغرق أي تقرير حقيقي بـ false positives.
**الإصلاح:** قصر القاعدة على `claim_type in {"performance", "dataset"}` فقط — الأنواع
المتوقع منها أصلًا أن تحمل قيمة رقمية.
**تحقق فعلي:** claim تقني نوعي بدون subject/property → لم يُشعل الـ flag. PASS.
(هذا الاكتشاف حصل فقط بعد رؤية ناتج حي فعلي من Gemini، وليس من المراجعة الثابتة للكود — درس
مهم: بعض المشاكل السلوكية لا تظهر إلا بتشغيل حقيقي.)

### Bug #4 (حرج، الأخطر) — ابتلاع `DailyQuotaExceeded` في 3 طبقات مختلفة من الـ pipeline
اكتُشف بالتسلسل عبر اختبار حي فعلي (وليس بالمراجعة الثابتة فقط):
- `evidence_general.py` و`plausibility.py` و`claim_extraction.py`: الـ `except Exception` العام
  كان يبتلع `DailyQuotaExceeded` (خطأ نظامي حقيقي) ويحوّله إلى `status="unclear"` عادي —
  يُخفي عن HR أن السبب هو فشل نظامي (quota) وليس غموضًا في المعلومة نفسها.
- **حتى بعد إصلاح الطبقات الثلاث أعلاه (بإضافة `except DailyQuotaExceeded: raise` قبل
  `except Exception`)**، اكتُشف Bug #4b: `app/pipeline/run.py` نفسه كان يحتوي `except Exception`
  عامة حول استدعاء `claim_extraction.extract_claims()` و`fact_check.verify_claims()`، فكانت
  تعيد تغليف `DailyQuotaExceeded` (429) داخل `FactCheckFailed`/`ClaimExtractionFailed` (502) —
  **إخفاء الخطأ الحقيقي من طبقة أعلى حتى بعد إصلاحه في الطبقة الأدنى.**
**الإصلاح النهائي:** إضافة `except AppError: raise` (يمسك أي خطأ معروف ومعبّر بالفعل، مثل
`DailyQuotaExceeded`) **قبل** `except Exception` العام في `run.py`، بحيث لا يُعاد تغليف أي
خطأ ذو معنى محدد سلفًا.
**تحقق فعلي (3 مستويات):**
1. اختبار محلي لكل من الطبقات الثلاث (`evidence_general.py`, `plausibility.py`,
   `claim_extraction.py`) — تأكيد أن `DailyQuotaExceeded` تُفلت بدون تحويل. PASS × 3.
2. اختبار محلي لـ `run.py` كامل (مع `extract_pptx.extract` مُموَّه) — تأكيد وصول
   `DailyQuotaExceeded` للأعلى دون تحويل. PASS.
3. **اختبار حي كامل عبر HTTP فعليًا:** رفع presentation حقيقي أثناء استنفاد الـ quota الفعلي
   → الرد النهائي للمستخدم أصبح `{"code": "DAILY_QUOTA_EXCEEDED", ...}` بدلاً من
   `{"code": "FACT_CHECK_FAILED", ...}` كما كان قبل الإصلاح. **هذا الاختلاف قبل/بعد شوهد
   فعليًا في استجابتين HTTP حقيقيتين متتاليتين لنفس الطلب.**

### الدرس العام من هذه الجلسة
مشكلة "ابتلاع الأخطاء المعبّرة داخل except عام" تكررت في **4 ملفات مختلفة** بنفس النمط بالضبط.
هذا يشير لضرورة قاعدة عامة صريحة تُضاف لـ `docs/DECISIONS.md`: **أي `except Exception` عام في
أي طبقة من طبقات الـ pipeline (`app/pipeline/*.py`) يجب أن يسبقه `except AppError: raise` (أو
استثناء محدد صريح لكل خطأ من `app/errors.py` متوقع الحدوث)، ولا يجوز أبدًا إعادة تغليف خطأ
مصنّف بالفعل داخل خطأ عام أقل دقة.**

### الحالة النهائية لـ Task 2.4, 2.5, 2.6
- [x] Task 2.4 — `evidence_general.py`: مُصلَّح (Bug #4) ومُختبر (محليًا + حيًا) ✅ DONE
- [x] Task 2.5 — `plausibility.py`: مُصلَّح (Bugs #1, #2, #3, #4) ومُختبر بالكامل (4 اختبارات محلية PASS) ✅ DONE
- [~] Task 2.6 — `run.py` + `postprocess.generate_correction`: الكود مُصلَّح (Bug #4b) ومُختبر
      منطقيًا بالكامل محليًا (PASS)، والمسار الكامل end-to-end تحقق منه حيًا **جزئيًا** (تأكدنا أن
      معالجة الأخطاء تعمل صح حيًا عبر HTTP فعليًا)، لكن **لم يُشاهَد بعد رد ناجح كامل يحتوي فعليًا
      على `correction` نصي متولّد من Gemini حي** لأن الـ quota نفدت أثناء الاختبار. **مطلوب: إعادة
      تشغيل نفس اختبار Task 2.6 بعد تعافي الـ quota (يوميًا الساعة 12 منتصف الليل بتوقيت المحيط
      الهادي أو عند توفر حصة جديدة) للتأكد النهائي من نص الـ correction الفعلي.**

---

## Task 2.3 — قرار مُراجَع + تنفيذ مختلف عن الخطة الأصلية

**الخطة الأصلية:** `app/providers/hf_provider.py` (embeddings محلية عبر Hugging Face).

**ما حدث فعليًا:** التحميل المحلي (نموذج ~2.2GB، مشاكل Windows-specific مع symlinks،
تعليق غير واضح المصدر أثناء التحميل) جعل هذا الخيار غير عملي في بيئة التطوير الفعلية.
تم اتخاذ قرار واعٍ بالتحول لاستخدام `gemini-embedding-001` (استقر رسميًا Generally
Available في 27 أغسطس 2026) عبر تفعيل `GeminiProvider.embed()` بدلاً من ترك
`NotImplementedError`.

**تم توثيق هذا كقرار مُراجَع صريح (وليس تعديلاً صامتاً) في `docs/DECISIONS.md` القسم 17**،
شاملاً المقايضات المقبولة (الخصوصية، استهلاك نفس الـ quota).

**تحقق فعلي:** استدعاء حي حقيقي عبر `GeminiProvider.embed()` — 3 نصوص، أبعاد 3072،
تشابه دلالي صحيح (0.912 للجمل المتشابهة، 0.603 للجملة غير المرتبطة). PASS.

**ملف `hf_provider.py`:** لم يُبنَ في هذه الجلسة (تم تجاوزه بالقرار المُراجَع أعلاه).
يبقى **مؤجلاً** وليس مطلوبًا للمسار الحالي، مع إبقاء الحقول ذات الصلة في
`config/settings.py` لمن يريد التبديل لاحقًا.

- [x] Task 2.3 (بالتنفيذ المُراجَع: Gemini embeddings بدل HF محلي) ✅ DONE

---

## Task 3.1 — تحويل الاختبارات اليدوية لـ pytest دائمة ✅ DONE

كل اختبار يدوي عملناه أثناء الـ bug fixing تحوّل لملف pytest رسمي في `tests/unit/`،
بحيث تفضل الإصلاحات الأربعة (من مراجعة Task 2.4/2.5/2.6) محمية بشكل دائم ضد أي رجوع
(regression) مستقبلي.

**الملفات الجديدة:**
- `tests/unit/test_plausibility.py` — يغطي: hard rules (percentage + 0-1 scale)،
  عدم تفعيل القاعدة على claims نوعية، فشل الـ AI يرجع unclear، الـ hard rule بتتخطى
  استدعاء الـ provider تمامًا.
- `tests/unit/test_error_propagation.py` — يغطي: `DailyQuotaExceeded` بتتسرب صح من
  `evidence_general.py` و`plausibility.py` و`run.py` كامل (الطبقات الثلاث + Bug #4b).
- `tests/unit/test_taxonomy_and_settings.py` — تكرار موسّع لاختبارات الـ taxonomy.
- `tests/unit/test_scoring.py` — أُعيدت كتابته بالكامل (كان الملف الأصلي متوافق مع
  شكل قديم لـ `compute_scores()` يرجع tuple، بينما الدالة الفعلية ترجع `Scores` واحدة
  فقط)، مع إضافة اختبارين جديدين (`not_checkable` مستبعد، قائمة فاضية = pass نظيف).

**النتيجة النهائية:** 25/25 اختبار PASS، صفر اعتماد على أي استدعاء شبكة حقيقي
(كل الاختبارات تعمل بـ `MagicMock` أو بيانات ثابتة، لا تستهلك أي Gemini quota).

---

## Task 2.6 — التحقق الحي النهائي ✅ DONE (لـ Track B بالكامل، Track A محدود بقيد بيئة موثّق)

بعد رحلة تشخيص طويلة (حساب شركة جديد → موديلات قديمة ممنوعة 404 → موديلات جديدة quota
ضيقة جدًا 429 → اكتشاف إن أداة grounding لها حصة منفصلة تمامًا عن التوليد العادي)، تم
الوصول لموديل نهائي مستقر: **`gemini-3.5-flash-lite`**.

**Track B (project-specific claims) — تحقق حي كامل وناجح 100%:**
presentation حقيقي بسلايدتين (claim بنسبة 99.9% مشبوهة + claim بحجم بيانات عادي) →
النتيجة: hard rule اشتغلت صح بدون استدعاء AI، Gemini حقيقي رجّع حكم سياقي بنص حقيقي
(مش stub)، السكور اتحسب صح 100% (تم التحقق يدويًا من كل رقم)، الـ issues والـ
interview questions اتبنوا صح.

**Track A (objective claims / grounding) — محظور حاليًا بقيد بيئة، ليس bug:**
أداة Google Search grounding لها quota منفصلة تمامًا وأضيق جدًا من التوليد النصي العادي
على حسابات Google Cloud الجديدة (تم تأكيد ذلك باختبار معزول: 4 استدعاءات نصية عادية
نجحت 4/4، استدعاء واحد بـ `use_grounding=True` فشل فورًا). **الحل: تفعيل Billing على
حساب Google Cloud** (ليس تعديل كود). `evidence_general.py` يتصرف بشكل صحيح تمامًا في
غياب الـ grounding — يرجع `unclear` بدلاً من اختلاق حكم، تمامًا كما صُمم.

**تحديث الموديل الافتراضي:** `config/settings.py` → `gemini_model` الافتراضي أصبح
`gemini-3.5-flash-lite` (كان `gemini-3.6-flash`).

**الحالة النهائية لـ Task 2.6:** ✅ مكتمل بما يخص بنية الكود والتحقق الممكن دون Billing.
Track A سيُعاد اختباره حيًا عند تفعيل Billing على الحساب.

---

## ملخص شامل: حالة المشروع عند نهاية هذه الجلسة

| Phase | الحالة |
|---|---|
| Phase 0 — Setup | ✅ مكتمل بالكامل، مُختبر |
| Phase 1 — Foundation | ✅ مكتمل بالكامل، مُختبر (25 unit test) |
| Phase 2 — Real AI (Gemini) | ✅ مكتمل — Track B مُتحقق منه حيًا بالكامل، Track A مُتحقق منه منطقيًا وجزئيًا حيًا (محدود بقيد Billing) |
| Phase 3.1 — Unit tests | ✅ مكتمل (25/25 PASS) |
| Phase 3.2/3.3 — Eval dataset | ⏳ لم يبدأ |
| Phase 4 — Polish | ⏳ لم يبدأ (فحص أمان أولي تم في هذه الجلسة) |
| Streamlit UI | ✅ مبني ومُختبر (بالـ stub، والواجهة تعاملت بشكل صحيح مع خطأ 429 حي) |

**Bugs حقيقية اكتُشفت وأُصلحت خلال المشروع: 4** (موثّقة بالتفصيل أعلاه في قسم "مراجعة عميقة").
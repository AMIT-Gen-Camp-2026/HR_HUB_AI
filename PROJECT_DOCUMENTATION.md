# PROJECT_DOCUMENTATION.md

هذه الوثيقة مبنية على قراءة المصدر التنفيذي المتتبع في Git وتشغيل الاختبارات في
9 سبتمبر 2026. ملفات `README.md` و`docs/*.md` والتعليقات القديمة ليست مصدر
الحقيقة هنا؛ استُخدمت فقط لتسجيل التعارضات عندما أمكن إثباتها مقابل الكود.

## 1. نظرة عامة

المشروع يعرّض خدمة Flask تستقبل CV بصيغة PDF أو DOCX وبيانات Job Description
في طلب multipart واحد. الخدمة تستخرج النص، تنظفه وتزيل PII قبل إرساله إلى
Hugging Face Inference Provider لاستخراج CV منظم، ثم تحسب درجة مطابقة deterministic
للمهارات المطلوبة والمفضلة.

### التقنية الفعلية

- Python: الإعداد يطلب `>=3.11`، لكن التشغيل المقاس محليًا كان Python `3.14.3`.
- Web: Flask 3، Flask-Limiter، WSGI app هو `app.main:app`.
- Validation: Pydantic 2 و`pydantic-settings`.
- Documents: `pdfplumber` و`python-docx`.
- Model provider: `huggingface_hub.InferenceClient` عبر `chat.completions`.
- Skill matching: YAML + PyYAML وRapidFuzz.
- Optional embeddings: `httpx` لـ OpenAI-compatible API أو `sentence-transformers` محليًا.
- UI: Streamlit و`requests`.
- التشغيل الإنتاجي في Docker: Gunicorn، workers=2.

## 2. البنية والـ call graph

### شجرة الملفات المتتبعة

الآتي هو جرد ملفات المشروع المتتبعة في Git، مع وصف مستنتج من محتواها الفعلي.
تم استبعاد `ai-service/.venv` وملفات cache المولدة لأنها ليست مصدرًا متتبعًا.

```text
.
|- .coverage                         coverage artifact متتبع
|- .gitignore                        قواعد تجاهل الجذر
|- CV_RANKING_BUG_ANALYSIS.md        تقرير قديم خارج المسار التنفيذي
|- CV_RANKING_BUG_FIX_REPORT.md      تقرير قديم خارج المسار التنفيذي
|- CV_RANKING_CHANGELOG.md           changelog قديم خارج المسار التنفيذي
|- cv_ranking_integration.md         عقد تكامل قديم/وصفي، لا يحدد التنفيذ
|- requirements.txt                  قائمة dependencies بديلة
|- ai-service/
   |- .coverage                      coverage artifact للخدمة
   |- .env.example                    أسماء وقيم مثال للإعدادات
   |- .github/CODEOWNERS              مالكو ملفات GitHub
   |- .github/pull_request_template.md قالب Pull Request
   |- .github/workflows/ci.yml       CI للـ lint/typecheck/secrets/tests/eval
   |- .gitignore                      قواعد تجاهل الخدمة
   |- .pre-commit-config.yaml         إعداد pre-commit
   |- .python-version                 إصدار Python المقترح
   |- Dockerfile                      image base وGunicorn وtarget hf
   |- Makefile                        أوامر install/run/test/lint/eval/docker
   |- README.md                       وصف قديم، ليس مصدر الحقيقة
   |- app/__init__.py                 فارغ
   |- app/main.py                    Flask app والـ endpoints
   |- app/pipeline/__init__.py        فارغ
   |- app/pipeline/extract_text_docx.py استخراج paragraphs والجداول من DOCX
   |- app/pipeline/extract_text_pdf.py  استخراج نص صفحات PDF
   |- app/pipeline/normalize.py       تنظيف Unicode/control chars والمسافات
   |- app/pipeline/postprocess.py     استخراج JSON وتطبيع حقول model output
   |- app/pipeline/ranking.py         مطابقة المهارات وحساب score
   |- app/pipeline/redact.py          إزالة identifiers وفحص outbound payload
   |- app/pipeline/run.py             orchestration وsnapshot cache
   |- app/prompts/__init__.py         فارغ
   |- app/prompts/registry.py         system/user prompts وحدود CV العشوائية
   |- app/providers/__init__.py       فارغ
   |- app/providers/embeddings.py     embedding providers وcosine similarity
   |- app/providers/hf_provider.py    استدعاء Hugging Face وfallback chain
   |- app/schemas/__init__.py         فارغ
   |- app/schemas/cv.py               Pydantic models الخاصة بـ CV/JD/ranking
   |- app/security/auth.py            X-API-Key decorator
   |- app/security/file_validator.py  extension/signature/storage-name validation
   |- app/skills/__init__.py          فارغ
   |- app/skills/canonicalize.py      taxonomy aliases وfuzzy matching
   |- app/skills/taxonomy.yaml        skill ids والأسماء والaliases
   |- config/settings.py              Config وSettings من environment/.env
   |- data/.gitkeep                   مجلد upload runtime فارغ في Git
   |- docker-compose.yml              خدمتا API وStreamlit
   |- docs/ARCHITECTURE.md            توثيق قديم
   |- docs/DECISIONS.md               قرارات قديمة
   |- docs/FULLSTACK_CHANGES_SINCE_LAST_HANDOFF.md توثيق قديم
   |- docs/FULLSTACK_INTEGRATION.md   توثيق قديم
   |- docs/PROMPTS.md                 توثيق قديم
   |- docs/PROVIDERS.md               توثيق قديم
   |- docs/RUNBOOK.md                 runbook قديم
   |- eval/README.md                  قواعد تقييم قديمة
   |- eval/__init__.py                فارغ
   |- eval/datasets/cv-extraction/v1/README.md وصف dataset
   |- eval/datasets/cv-extraction/v1/labels.jsonl ملف labels فارغ فعليًا
   |- eval/reports/.gitkeep            مجلد تقارير فارغ
   |- eval/runners/__init__.py        فارغ
   |- eval/runners/run_extraction.py  loader CLI ثم Not implemented
   |- eval/runners/run_ranking.py     metric Agreement@k وbaseline
   |- notebooks/README.md             ملاحظة notebooks، لا notebooks متتبعة
   |- pyproject.toml                  package/dependencies/tools/pytest config
   |- scripts/README.md               وصف scripts
   |- scripts/check_embeddings.py     فحص provider فعليًا
   |- tests/__init__.py               فارغ
   |- tests/fixtures/README.md        سياسة fixtures وتغطية مطلوبة
   |- tests/fixtures/tc001/candidate.pdf fixture PDF
   |- tests/fixtures/tc001/jd.json    JD grouped structure فعلية
   |- tests/integration/__init__.py   فارغ
   |- tests/integration/test_auth.py  خمس اختبارات auth/health/open mode
   |- tests/integration/test_rank_endpoint.py ثمانية اختبارات endpoint
   |- tests/unit/__init__.py          فارغ
   |- tests/unit/test_canonicalize.py خمس اختبارات taxonomy
   |- tests/unit/test_embeddings.py   اختبار ترتيب API vectors
   |- tests/unit/test_extraction_snapshot.py أربعة اختبارات cache
   |- tests/unit/test_extraction_status.py اختبار EMPTY/SUCCESS
   |- tests/unit/test_hf_provider.py  اختبار fallback metadata
   |- tests/unit/test_ranking.py      تسعة عشر اختبارًا للـ scoring
   |- tests/unit/test_redaction.py    ثلاثة اختبارات redaction/assertion
   |- tests/unit/test_redaction_integration.py اختباران لعدم تسريب PII
   |- ui/streamlit_app.py             واجهة upload وعرض extraction/ranking
```

### المسار الحي للـ API

```text
POST /api/v1/cv/evaluate
  -> require_api_key
  -> Flask-Limiter (10/hour، مع default app limit 30/hour)
  -> validate form fields + json.loads(job_description)
  -> JobDescription
  -> validate_extension -> generate_safe_storage_name -> file.save
  -> validate_file_content
  -> extract_raw_text
       .pdf  -> extract_text_from_pdf
       .docx -> extract_text_from_docx
  -> clean_and_query
       -> clean_cv_text
       -> extract_contact_info
       -> snapshot lookup
       -> redact -> build_prompt -> assert_clean
       -> query_model
            -> _call_model لكل model في chain
            -> parse_and_validate
                 -> extract_json_from_model_output
                 -> normalize_model_output
                 -> CVSchema
       -> extract_explicit_skills + snapshot store
       -> restore local email/phone
  -> extraction_status
  -> rank (only when non-empty and RANKING_ENABLED)
  -> jsonify
  -> finally remove temporary file
```

### Ranking pipeline

```text
CVSchema + JobDescription
  -> جمع skills + inferred_skills + project technologies + experience job_title
  -> canonicalise لكل قيمة (taxonomy exact/alias ثم WRatio >= 92)
  -> إزالة تكرار JD مع الحفاظ على الترتيب
  -> canonical match أو raw exact/substring match
  -> required_ratio و nice_ratio
  -> hard_skill_score
  -> semantic_fit لا يُستدعى فعليًا لأن SEMANTIC_WEIGHT = 0.0
  -> score = hard_skill_score * 1.0 + 0.0
```

### كود موجود لكنه ليس في المسار الحي

- `app.providers.embeddings.semantic_fit` قابل للاستدعاء ومختبر جزئيًا، لكن
  `ranking.rank` لا يستدعيه مع الثابت الحالي `SEMANTIC_WEIGHT = 0.0`.
- `eval.runners.run_extraction` يقرأ labels ثم ينتهي برسالة `Not implemented`.
- `eval.runners.run_ranking` ليس مستوردًا من Flask؛ يعمل فقط كـ CLI ومع dataset
  مناسب، لكن dataset المتاح هنا هو dataset extraction فارغ.
- `scripts/check_embeddings.py` وStreamlit UI أدوات تشغيل منفصلة وليستا جزءًا من
  import path الخاص بـ `app.main`.
- `RankingRequest` موجود في schema ولا يُستخدم في route.

## 3. الـ Endpoints والـ API

### `GET /api/v1/health`

- لا body ولا query parameters.
- يرجع دائمًا من handler: `{"status": "ok"}`, status `200`.
- لا يمر بـ `require_api_key`.
- يظل خاضعًا عمليًا للـ default app rate limit `30 per hour` من Flask-Limiter،
  لأن الكود لا يستثنيه.

### `POST /api/v1/cv/evaluate`

الطلب `multipart/form-data` ويحتاج:

- `file`: ملف له filename غير فارغ، امتداده `.pdf` أو `.docx` بعد lowercase.
- `job_description`: قيمة form string تُمرر إلى `json.loads` ويجب أن تنتج object.
  الحقول المطلوبة داخل object: `title: str` و`required_skills: List[str]`.
  `nice_to_have_skills` default `[]`، و`min_experience_years` اختياري `int`.
- Header `X-API-Key` مطلوب فقط عندما يكون `AI_SERVICE_API_KEY` غير فارغ؛ المقارنة
  تستخدم `hmac.compare_digest`. عندما يكون الإعداد فارغًا، auth fail-open مع warning
  واحد.

تسلسل التنفيذ والردود:

1. غياب `file`: JSON `{success:false,error:...}`, `400`.
2. filename فارغ: `400`.
3. غياب `job_description`: `400`.
4. JSON غير صالح: `400`.
5. JSON ليس object: `400`.
6. فشل `JobDescription`: `422` مع `e.errors()`.
7. extension أو magic bytes غير صالحين: `400`.
8. بعد الحفظ المؤقت، استخراج نص فارغ: `422`.
9. فشل كل model attempts أو output validation: `502` مع `extraction_status: FAILED`.
10. CV صالح لكنه بلا evidence: `200`، `extraction_status: EMPTY` و`ranking: null`.
11. `RANKING_ENABLED` false: `200`، CV وmetadata و`ranking: null`.
12. exception غير متوقع في ranking أو بقية المسار: `500`.
13. النجاح مع ranking: `200` ويحتوي `success`, `cv`, `ranking`,
    `extraction_status: SUCCESS`, و`extraction_metadata`.

كل رد error من handler يستخدم envelope `success: false` و`error`. حد Flask
`MAX_CONTENT_LENGTH` هو 10 MiB، وقد ينتج رفض Flask قبل دخول handler للطلبات الأكبر.
الـ endpoint عليه limit خاص `10 per hour`، إضافة إلى default app limit `30 per hour`.

## 4. الخوارزميات والمنطق الأساسي

### Extraction

- `extract_text_from_pdf(path)`: يفتح PDF، يرفض عدم وجود صفحات أو عدم وجود نص،
  ويجمع صفحات النص بـ newline. يستخدم `x_tolerance=1`. فشل صفحة واحدة يطبع
  تحذيرًا ويكمل، لكن إذا لم يبق نص يرفع `PDFExtractionError`.
- `extract_text_from_docx(path)`: يجمع paragraphs غير الفارغة ثم كل cell في الجداول.
  الملف غير الموجود يرفع `FileNotFoundError`، وفشل القراءة أو النص الفارغ يرفع
  `DOCXExtractionError`.
- `clean_cv_text`: NFKC، إزالة control/bidi chars، توحيد المسافات، تقليل الأسطر
  الفارغة، trim، ثم قص إلى `MAX_TEXT_LENGTH = 20000` حرفًا.
- `extract_json_from_model_output`: يبحث عن أول `{` ويحسب braces مع احترام strings
  والـ escapes؛ يحلل أول object متوازن فقط. النص الفارغ أو JSON المبتور/غير الصالح
  يرفع `JSONExtractionError`.
- `normalize_model_output`: يحول `position/role/title` إلى `job_title`، و`year`
  إلى `graduation_year`، يستنتج سنة من `end_date` أو `start_date` في education،
  ويحذف الحقول غير المسموحة في experience/education/projects.
- `query_model`: يحاول `MODEL_CHAIN + [MODEL_CHAIN[0]]`، أي primary ثم fallback
  ثم retry للـ primary. فشل الشبكة وفشل `validate_fn` كلاهما ينتقلان للمحاولة التالية.

### Snapshot cache

`clean_and_query` يستخدم SHA-256 للنص المنظف مع prompt/schema/taxonomy/model config
كمفتاح. cache in-memory، TTL=`3600.0` ثانية، وسعة=`128` entry مع LRU eviction.
الـ metadata يكشف `cache_hit`, model/provider, attempt number وskills المستعادة.

### Ranking formula

الثوابت الحالية في `app/pipeline/ranking.py`:

```text
REQUIRED_WEIGHT = 0.8              # معلن لكنه لا يدخل الحساب الحالي
NICE_TO_HAVE_WEIGHT = 0.2
HARD_SKILL_WEIGHT = 1.0
SEMANTIC_WEIGHT = 0.0

required_ratio = matched_required / len(required) أو None إذا كانت القائمة فارغة

إذا كان هناك required:
  preferred_bonus = 0.2 * (nice_ratio أو 0) * (1 - required_ratio)
  hard_skill_score = required_ratio + preferred_bonus
وإلا:
  hard_skill_score = 0.2 * (nice_ratio أو 0)

fit = 0.0 لأن SEMANTIC_WEIGHT = 0.0
fit_clamped = max(0, min(1, fit))
final_score = 1.0 * hard_skill_score + 0.0 * fit_clamped
score = round(final_score * 100, 2)
```

المطابقة canonical أولًا، ثم raw case-insensitive exact/substring ثنائي الاتجاه؛
الـ substring لا يُستخدم عندما يكون الطرف القصير أقل من 4 أحرف. يُزال تكرار JD
بـ canonical id أو casefolded display مع الحفاظ على ترتيبها. `min_experience_years`
يُتحقق منه Pydantic لكنه لا يدخل في ranking.

`semantic_fit` نفسه يبني profile من skills/inferred skills/job titles/projects،
وJD من title والمهارات، ويحسب cosine similarity بعد embedding. هذا المسار
non-deterministic/خارجي عند API أو model محلي، لكنه غير مؤثر على score الحالي.
أما extraction فغير deterministic بسبب LLM خارجي و`secrets.token_hex` للـ delimiter؛
cache قد يجعل النتيجة ثابتة مؤقتًا لنفس configuration.

## 5. Schema / Data Contracts

كل models ترث `StrictModel` بإعداد `ConfigDict(extra="ignore")`، أي الحقول
الإضافية تُهمل ولا تُرفض.

- `PersonalInfo`: `name`, `email`, `phone`, `location`, `linkedin`, `github`، كلها
  `Optional[str] = None`.
- `Education`: `degree`, `institution`, `graduation_year`، كلها optional string.
- `Experience`: `job_title`, `company`, `start_date`, `end_date`، كلها optional string.
- `Project`: `name`, `description` optional string؛ `technologies_mentioned: List[str]`
  default factory list.
- `CVSchema`: `personal_info` default `PersonalInfo()`؛ القوائم
  `education`, `experience`, `projects`, `skills`, `inferred_skills`,
  `certifications`, `languages` كلها default factory lists.
- `JobDescription`: `title: str` و`required_skills: List[str]` required؛
  `nice_to_have_skills: List[str] = []`؛ `min_experience_years: Optional[int] = None`.
  validator قبل البناء يقبل legacy `job_title`, يحول required dict إلى list،
  ويقبل `preferred_qualifications` كـ nice-to-have.
- `RankingRequest`: `candidate: CVSchema`, `job_description: JobDescription`؛ موجود
  لكنه غير مستخدم في HTTP route.
- `RankingResult`: `score: float`, `matched_skills: List[str]`,
  `missing_skills: List[str]`, أربع قوائم تفصيلية default empty،
  `semantic_fit: Optional[float] = None`, و`breakdown: dict` required.
- `EMPTY_CV_SCHEMA`: dump لـ `CVSchema()` ويُستخدم لبناء prompt schema.

## 6. الأمان والحماية

| الآلية | التنفيذ | الحالة في المسار الحي |
|---|---|---|
| API key | `require_api_key`، header `X-API-Key` و`compare_digest` | Active على evaluate؛ fail-open إذا الإعداد فارغ |
| File extension | allowlist `.pdf`, `.docx` | Active قبل الحفظ |
| Magic bytes | `%PDF-` و`PK\\x03\\x04` | Active بعد `file.save` |
| Safe temp name | `secure_filename` + UUID | Active، والملف يحذف في `finally` |
| Request size | Flask `MAX_CONTENT_LENGTH = 10 MiB` | Active قبل/أثناء Flask parsing |
| Rate limiting | 30/hour default و10/hour evaluate، in-memory | Active، غير موزع بين workers |
| Text normalization | إزالة control وbidi chars، حد 20000 حرفًا | Active قبل prompt |
| PII redaction | email، رقم مصري، national ID، long digits | Active قبل بناء prompt |
| Outbound assertion | `assert_clean(system_prompt + user_prompt)` | Active؛ يفشل الإرسال إذا تسرب pattern |
| Prompt injection rules | system prompt + randomized delimiters | Active كتعليمات للموديل، ليست ضمانًا تنفيذيًا |
| Embedding API key | `GEMINI_API_KEY` في request header | موجود فقط داخل مسار embeddings غير المؤثر على ranking |

`redact.py` ليس orphaned كما قد توحي بعض الوثائق القديمة؛ `run.clean_and_query`
يستدعيه فعليًا. في المقابل، `semantic_fit` وembedding provider موجودان لكن غير
مستخدمين في النتيجة الحالية بسبب weight صفر.

## 7. الاختبارات

| الملف | العدد | النطاق |
|---|---:|---|
| `tests/integration/test_auth.py` | 5 | API key، health، fail-open |
| `tests/integration/test_rank_endpoint.py` | 8 | evaluate، validation، kill switch، metadata |
| `tests/unit/test_canonicalize.py` | 5 | aliases وexplicit scan |
| `tests/unit/test_embeddings.py` | 1 | ترتيب API vectors |
| `tests/unit/test_extraction_snapshot.py` | 4 | hit، config change، TTL، eviction |
| `tests/unit/test_extraction_status.py` | 1 | EMPTY/SUCCESS |
| `tests/unit/test_hf_provider.py` | 1 | fallback metadata |
| `tests/unit/test_ranking.py` | 19 | scoring والمطابقة والـ legacy JD |
| `tests/unit/test_redaction.py` | 3 | redaction وassertion |
| `tests/unit/test_redaction_integration.py` | 2 | عدم إرسال PII واستعادة contact |
| **الإجمالي** | **49** | |

التشغيل الفعلي:

```text
python ai-service/.venv/Scripts/python.exe -m pytest
49 passed, 1 warning in 3.02s
```

التحذير من Flask-Limiter بسبب استخدام in-memory storage. التشغيل بـ `python -m
pytest` من Python العالمي لم يكن نتيجة اختبار: توقف أثناء تحميل plugin خارجي؛
النتيجة المعتمدة أعلاه من بيئة المشروع.

مسارات غير مغطاة أو تغطيتها محدودة: استخراج PDF/DOCX الحقيقي، استدعاء Hugging
Face الحقيقي، parsing JSON غير الصالح في اختبارات مباشرة، فروع exceptions العامة
في route، rate-limit behavior، `RANKING_ENABLED` default من environment، UI،
`run_ranking` CLI، وembedding المحلي/API كاملًا. لا يوجد dataset تقييم extraction
يمكن تشغيله.

## 8. الفجوات والتعارضات

| العنصر | الحالة الموثقة قديمًا | الحالة الفعلية في الكود | الفجوة |
|---|---|---|---|
| HTTP framework | بعض docs القديمة تشير إلى FastAPI | `app.main` Flask وGunicorn WSGI | التوثيق القديم غير مطابق |
| endpoint contract | التكامل يصف evaluate فقط، وهذا الجزء متوافق | لا توجد routes extract/rank منفصلة في `app.main` | لا يوجد split endpoint فعلي |
| score weights | أمثلة قديمة تعرض semantic weight | `HARD_SKILL_WEIGHT=1.0`, `SEMANTIC_WEIGHT=0.0` | semantic لا يغير score؛ `REQUIRED_WEIGHT=0.8` غير مستخدم |
| PII redaction | بعض التعليقات تصف module كحماية | `clean_and_query` يستدعي redact وassert_clean | الحالة الفعلية أفضل من وصف orphaned قديم |
| evaluation dataset | الهدف 100 CV في README dataset | `labels.jsonl` فارغ (0 rows) | لا يمكن استخراج metric أو تشغيل CI evaluation بنجاح |
| extraction evaluation | CI يشغل `run_extraction` | runner ينتهي `Not implemented` بعد load | خطوة CI لا تنتج metric فعليًا |
| ranking evaluation | موثق كـ Agreement@k | metric code موجود، لكن لا يوجد ranking dataset في الشجرة | metric غير قابل للتشغيل من البيانات الحالية |
| `AI_SERVICE_URL` | compose يمرره للـ UI | UI يستخدم `BASE_URL = http://127.0.0.1:5000` ولا يقرأ المتغير | UI داخل compose قد لا يصل إلى service عبر الاسم |
| dependencies | `requirements.txt` وpyproject كلاهما قوائم كاملة | بينهما اختلافات؛ `requests` مستخدم في UI لكنه ليس dependency مباشرًا في pyproject، و`pyarabic` غير مستورد، و`openai`/`google-genai` في requirements غير مستوردين | مصدر install غير موحد واعتماديات معلنة زائدة/ناقصة |
| Docker | image base يثبت `.[ui]` ويشغل Gunicorn | لا يثبت `[dev]` ولا `[eval]` ولا `[hf]`؛ local sentence-transformers غير متاح في base | التشغيل يعتمد على provider/config خارجي؛ targets لا تشمل test/eval |
| Redis | compose لا يشغله | limiter in-memory كما يحذر الاختبار/runtime | rate limiting ليس shared بين workerين |
| `min_experience_years` | جزء من JD schema | يُقبل ويُعاد في model لكنه لا يدخل score | contract يوحي بقيد لا ينفذ في ranking |
| coverage threshold | pyproject يذكر fail-under 49 | suite مرّت لكن تقرير coverage الكامل ليس جزءًا من نتيجة pytest المعروضة هنا | الرقم يحتاج تشغيل coverage منفصل لتأكيده |

## 9. نقاط القوة الحالية

- route واحد يربط extraction وranking ويمنع ranking عند extraction الفارغ أو الفاشل.
- الملف يتحقق بالامتداد وبـ magic bytes، ويخزن باسم UUID مؤقت ثم يحذفه في `finally`.
- PII يُستخرج محليًا قبل redaction ويُعاد إلى schema بعد إرسال النص المنقح؛ اختبارات
  التكامل تتحقق أن email/phone/national ID لا يصل إلى prompt.
- fallback chain تعتبر فشل validation فشلًا حقيقيًا، وتعيد metadata عن model/provider
  والمحاولة.
- ranking الحالي reproducible ولا يتأثر بمزود embeddings لأن semantic weight صفر،
  مع إبقاء evidence التفصيلي للـ required والـ preferred.
- canonicalization تجمع aliases وتستخدم fuzzy threshold مرتفعًا (`92`) وتعيد `None`
  للمجهول بدل اختراع id.
- snapshot key يتضمن النص ونسخ prompt/schema/taxonomy وmodel configuration، مع TTL
  وحد أقصى، وتغطي الاختبارات hit/expiry/eviction.
- suite الحالية نجحت بالكامل: 49 اختبارًا.

## 10. نقاط الضعف والمخاطر الحالية

- auth fail-open إذا كان `AI_SERVICE_API_KEY` فارغًا؛ هذا يترك evaluate بلا حماية.
- limiter in-memory مع Gunicorn workers=2؛ الحد ليس مشتركًا بين workers ويُفقد عند restart.
- extraction يعتمد على خدمة LLM خارجية، token وtimeout وfallback؛ لا يوجد اختبار
  اتصال حقيقي أو ضمان deterministic للمخرجات.
- `MAX_TEXT_LENGTH` يقص النص بصمت، وقد يسقط معلومات من CV طويل.
- redaction regex مخصص لأشكال معينة؛ `assert_clean` لا يفحص كل أنواع PII الممكنة.
- ranking لا يستخدم `min_experience_years` ولا semantic fit؛ score مهارات فقط، مع
  constant `REQUIRED_WEIGHT` المعلن غير المستخدم.
- taxonomy نفسها تحتوي تعليقات تفيد أن إضافات Sprint 2 مبنية على تخمين، كما أن
  canonicalization fuzzy قد تربط مصطلحًا قريبًا خطأ عند threshold 92.
- لا يوجد تقييم extraction قابل للتشغيل لأن labels فارغ وrunner غير منفذ، ولا توجد
  benchmark ranking rows في الشجرة.
- مسار UI يحقن عناصر HTML من قيم CV عبر `unsafe_allow_html=True` في `display_list`
  وبعض بطاقات المعلومات؛ القيم ليست escaped قبل إدخالها إلى HTML.
- UI يثبت `BASE_URL` على loopback ويتجاهل `AI_SERVICE_URL` الذي يمرره compose.
- `requirements.txt` و`pyproject.toml` غير متطابقين، ووجود `.venv` المتتبعة/الموجودة
  محليًا يزيد احتمال اختلاف Python والـ plugins عن CI.
- Docker ينسخ `app`, `config`, `ui` فقط؛ لا ينسخ tests/eval، لذلك صورة التشغيل لا
  تحمل أدوات القياس أو fixtures.

## 11. خريطة التغييرات الأخيرة

### آخر commits المتاحة

السجل المتاح على الفرع `cv-review`:

```text
b683557 edit tokens
e42f3ed bugs fixed
fab5b43 edit endpoints
5dbae86 edit
0f32c5a edit for integration
f97a1bd Add CV review project
```

الأسماء المختصرة لا تكفي لإثبات مضمون كل commit دون قراءة diff كامل؛ لذلك لا
أنسب تغييرات ملفية دقيقة إلى commit بعينه هنا. آخر commit هو `b683557`.

### Working tree

فحص `git status --short --untracked-files=all` قبل إنشاء هذه الوثيقة لم يُظهر
ملفات معدلة أو untracked. الملف الحالي `PROJECT_DOCUMENTATION.md` هو التغيير
الجديد الناتج عن هذه المهمة.

## أمثلة تنفيذية قصيرة

الـ route يفعّل ranking فقط بعد extraction غير الفارغ:

```python
status = extraction_status(validated_cv)
if status == "EMPTY" or not config.RANKING_ENABLED:
    ranking = None
else:
    ranking = compute_ranking(validated_cv, job_description)
```

والحماية من إرسال PII تقع قبل `build_prompt`:

```python
redacted_text, _ = redact(cleaned_text)
system_prompt, user_prompt = build_prompt(redacted_text)
assert_clean(system_prompt + user_prompt)
```

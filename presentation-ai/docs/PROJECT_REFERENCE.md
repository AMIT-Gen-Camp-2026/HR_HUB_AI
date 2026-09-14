# Presentation AI: Project Reference

This document describes the implementation currently in this repository. It is intended to stand alone for an engineer planning integration with a separate Demo AI system. Where an older document describes a plan that differs from the code, the code and the saved evaluation artifacts win.

## 1. Plain-language summary

Presentation AI accepts one PowerPoint `.pptx` presentation, extracts the content of its slides, identifies factual or quantitative claims, classifies each claim, and verifies it through one of two tracks. It returns a structured JSON report containing the claims, verification results, evidence where available, scores, issues, and suggested interview questions. It supports Arabic, English, and mixed-language slide content at the normalization and prompt-input level.

The report is intended for HR or an interviewer before an interview or technical demo. It helps a human see what the applicant asserted, which general claims have external evidence, which project claims deserve scrutiny, and where follow-up questions may be useful. It is decision support only: it never makes an accept/reject hiring decision. A human remains responsible for that decision.

The system does not analyze speech, video, or the live demo; those belong to the separate Demo AI system. It also cannot establish the truth of an applicant's private project results from the presentation alone. Project-specific verification is a plausibility and internal-consistency assessment, not proof.

## 2. End-to-end pipeline

The live orchestration is `app/pipeline/run.py`, in this order:

1. **HTTP upload validation.** `app/api/routes_presentation.py` requires a non-empty `.pptx`, sanitizes its filename, and checks the ZIP magic bytes. This is deterministic. The route then delegates to the pipeline and serializes the Pydantic result as JSON.
2. **PPTX extraction.** `app/pipeline/extract_pptx.py` parses slides with `python-pptx` and records slide number, title, text, tables, charts, and speaker notes. This is deterministic because it reads the package; it does not interpret whether a claim is true.
3. **Normalization.** `app/pipeline/normalize.py` applies Unicode NFKC normalization, selected Arabic character normalization, whitespace cleanup, and within-slide duplicate-element removal. This is deterministic. It preserves numbers, units, negation, and slide identity.
4. **Claim extraction and classification.** `app/pipeline/claim_extraction.py` calls the configured provider once for each non-empty slide and renders `claim_extract.v3.jinja`. The model returns claim text, type, track, importance, and optional canonical fields; this is AI-driven because interpreting slide language into claims is semantic. Despite older documentation saying extraction is batched, the current implementation is one slide per provider call.
5. **Track dispatch and verification.** `app/pipeline/fact_check.py` sends objective claims to Track A and project-specific claims to Track B. Track A uses `fact_check.v1.jinja` plus provider grounding; Track B performs deterministic arithmetic and hard-rule checks first, then uses `plausibility_judgment.v2.jinja` in batches of four for the remaining claims. The checks are therefore mixed deterministic/AI-driven.
6. **Deterministic scoring.** `app/pipeline/scoring.py` converts statuses and importance into weighted scores. No provider is called, so identical inputs produce identical scores.
7. **Contradicted-only corrections.** For each contradicted claim with evidence, `app/pipeline/postprocess.py` calls `correction_generate.v1.jinja`. This is AI-driven and evidence-constrained; no correction is generated for other statuses or for a contradicted claim without evidence.
8. **Issues and questions.** The same module deterministically assigns issue severity and builds issues. It also builds interview questions, including a mandatory question for each `plausibility_flag`; the question text is generated from deterministic templates in code, not an LLM prompt.
9. **Summary and final JSON.** `run.py` counts statuses, calculates completeness, sets `status` to `completed` or `partial` based on failed slides, creates a random analysis ID, and returns `PresentationAnalysisResult`. This assembly is deterministic.

## 3. Complete file-by-file reference

The entries below cover the source, configuration, evaluation, template, and documentation files in the requested directories. `__init__.py` files are package markers with no application behavior. The `.pyc` files are generated caches and are not part of the source contract. The PPTX files under the evaluation dataset are input fixtures; their labels are described below.

### `app/api/`

- `app/api/__init__.py` — Package marker. Deterministic; no key functions.
- `app/api/routes_health.py` — Exposes the health endpoint and reports application/provider readiness. Deterministic; key function: `health`.
- `app/api/routes_presentation.py` — Defines `POST /api/v1/presentation/analyze`, validates the upload, calls `run_presentation_analysis`, and returns `model_dump()` JSON. Deterministic HTTP plumbing; key function: `analyze`.

### `app/`

- `app/__init__.py` — Package marker. Deterministic.
- `app/errors.py` — Defines application exception classes used for invalid files, extraction, claim extraction, fact checking, and scoring failures. Deterministic; no prompt.
- `app/main.py` — Creates the Flask application, loads settings/prompts/provider, registers blueprints, and installs error handling. Deterministic wiring; it selects a provider but does not itself interpret claims.
- `app/telemetry.py` — Defines in-memory call records and helpers used to capture provider stage, model, token, and error information. Deterministic bookkeeping; key functions include `record_call`, `get_session_records`, and `reset_session_records`.

### `app/pipeline/`

- `app/pipeline/__init__.py` — Package marker. Deterministic.
- `app/pipeline/extract_pptx.py` — Converts PPTX bytes into `ExtractedPresentation`, `SlideContent`, and `SlideElement` records. It distinctly extracts `text`, `table`, `chart`, and `note` elements and preserves `slide_number`. Deterministic; key function: `extract`.
- `app/pipeline/normalize.py` — Cleans extracted text and flattens a slide into prompt text with `[Text]`, `[Table]`, `[Chart]`, and `[Speaker Note]` prefixes. Deterministic; key functions: `normalize`, `slide_to_prompt_text`.
- `app/pipeline/claim_extraction.py` — Calls `claim_extract.v3.jinja` per non-empty slide, validates/coerces provider output, canonicalizes known properties, and assigns sequential IDs. AI-driven for extraction/classification; key functions: `extract_claims`, `_coerce_claim`.
- `app/pipeline/fact_check.py` — Dispatches objective claims to evidence verification and project claims to batched plausibility verification. Deterministic dispatch; the called Track A/B modules are AI/mixed. Key function: `verify_claims`.
- `app/pipeline/evidence_general.py` — Renders `fact_check.v1.jinja`, requests grounding, requires a source and confidence at least `0.75` for supported/contradicted, and downgrades unsupported verdicts to `unclear`. AI-driven; key function: `verify`.
- `app/pipeline/plausibility.py` — Implements Track B arithmetic checks, hard rules, batched contextual judgments, fallback individual judgments, and evidence for internal math. Mixed deterministic/AI; uses `plausibility_judgment.v2.jinja` for batches and `plausibility_judgment.v1.jinja` only in fallback. Key functions: `check_internal_math_consistency`, `hard_rules`, `verify_batch`.
- `app/pipeline/scoring.py` — Pure importance-weighted status scoring and score aggregation. Deterministic; key function: `compute_scores`.
- `app/pipeline/postprocess.py` — Generates evidence-based corrections using `correction_generate.v1.jinja`, assigns issue severity, builds issues, and creates interview questions. Corrections are AI-driven; issue/question assembly is deterministic. Key functions: `generate_correction`, `assign_severity`, `build_issues`, `build_interview_questions`.
- `app/pipeline/run.py` — The end-to-end orchestrator described in Section 2. Mixed overall; key function: `run_presentation_analysis`.

### `app/providers/`

- `app/providers/__init__.py` — Package marker. Deterministic.
- `app/providers/base.py` — Defines the `ProviderAdapter` interface, `CompletionResult`, and provider abstraction for text completion and embeddings. Deterministic contract; no prompt template itself.
- `app/providers/factory.py` — Instantiates `api`, `hf`, `local`, or `stub` provider from settings. Deterministic selection; key function: `build_provider`.
- `app/providers/api_provider.py` — Adapter for the configured Gemini API, including optional grounding and embeddings. AI/network-driven when selected; it receives rendered prompts from pipeline modules.
- `app/providers/hf_provider.py` — Hugging Face adapter for local Transformers or inference API operation. AI/network or local-model driven when selected; no pipeline-specific prompt ownership.
- `app/providers/local_provider.py` — OpenAI-compatible local model adapter using the configured local base URL/model. AI-driven when selected; no pipeline-specific prompt ownership.
- `app/providers/stub_provider.py` — Canned deterministic provider used by tests and smoke runs; it returns fixed claim, plausibility, fact-check, correction, and zero-vector embedding responses. Not a real AI measurement and makes no network calls. Key class: `StubProvider`.
- `app/providers/embeddings.py` — Hash-caches calls to `provider.embed`; it is a utility only. It is not called by the presentation pipeline, so there is no embedding-based claim matching in the current product flow. Key function: `embed_cached`.

### `app/schemas/`

- `app/schemas/__init__.py` — Re-exports both presentation and cross-modal schema classes, so importing the `app.schemas` package loads `integration.py` indirectly. It is deterministic package wiring; the live pipeline imports `app.schemas.presentation` directly and does not use the cross-modal models.
- `app/schemas/presentation.py` — Defines the current presentation API contract: `Claim`, `ClaimVerification`, `Evidence`, `Correction`, `Issue`, `Scores`, `Summary`, `InterviewQuestion`, metadata models, and `PresentationAnalysisResult`. Deterministic Pydantic validation; no prompt.
- `app/schemas/integration.py` — Defines future cross-modal integration models (`SpokenClaim`, `ClaimAlignment`, `CrossModalSummary`, `CrossModalAnalysisResult`) against Demo AI's verified transcript output contract. It is imported indirectly by `app.schemas.__init__`, but no file under `app/pipeline/` or `app/api/` imports or uses these models, and the current presentation pipeline does not produce or consume them. Deterministic; no prompt.

### `app/prompts/`

- `app/prompts/__init__.py` — Package marker. Deterministic.
- `app/prompts/registry.py` — Loads Jinja templates and renders a named version. Deterministic; key class: `PromptRegistry`.
- `app/prompts/templates/claim_extract.v1.jinja` — Older claim extraction prompt. Not used by the current orchestrator.
- `app/prompts/templates/claim_extract.v2.jinja` — Older claim extraction prompt. Not used by the current orchestrator.
- `app/prompts/templates/claim_extract.v3.jinja` — Current per-slide extraction/classification prompt used by `claim_extraction.py`.
- `app/prompts/templates/fact_check.v1.jinja` — Current objective-claim fact-check prompt used with provider grounding.
- `app/prompts/templates/plausibility_judgment.v1.jinja` — Single-claim Track B prompt used by fallback after a batch failure.
- `app/prompts/templates/plausibility_judgment.v2.jinja` — Current batch Track B prompt, up to four claims per provider call.
- `app/prompts/templates/correction_generate.v1.jinja` — Current evidence-based correction prompt for contradicted claims.

### `app/taxonomy/`

- `app/taxonomy/__init__.py` — Package marker. Deterministic.
- `app/taxonomy/canonicalize.py` — Validates known claim types and canonicalizes property names. Deterministic; key functions include `is_known_claim_type` and `canonicalize_property`.
- `app/taxonomy/claim_taxonomy.yaml` — Data file defining the claim taxonomy/property vocabulary used by canonicalization. Deterministic configuration.

### `config/`

- `config/__init__.py` — Package marker. Deterministic.
- `config/settings.py` — Pydantic settings loaded from environment, including provider, Gemini/local/HF settings, feature flags, pacing, batch sizes, and port. Deterministic configuration; key class/function: `Settings`, `get_settings`. `claim_batch_size=5` exists but is not used by current extraction; Track B uses `BATCH_SIZE=4` in code.
- `config/providers.yaml` — Provider configuration data. Deterministic configuration; provider instantiation is performed by `app/providers/factory.py`.
- `config/logging.yaml` — Logging configuration. Deterministic configuration.

### `eval/`

- `eval/__init__.py` — Package marker. Deterministic.
- `eval/README.md` — Explains the labeled evaluation dataset and evaluation workflow. Documentation; it is not runtime behavior.
- `eval/run_live_eval.py` — Older live-evaluation entry point. It is stale relative to the current result/schema fields and should not be treated as the authoritative runner.
- `eval/runners/__init__.py` — Package marker. Deterministic.
- `eval/runners/run_extraction.py` — Current labeled-dataset runner: extracts claims, greedily matches predicted text to labels, computes extraction/classification/verification/plausibility metrics, and writes JSON results. Mixed because it invokes the configured provider; key functions include `match_claims`, `evaluate_file`, `aggregate`, and `main`.
- `eval/scripts/build_v1_presentations.py` — Builds the version-one PPTX evaluation fixtures. Deterministic fixture generation.
- `eval/scripts/probe_grounding.py` — Small grounding/provider probe used to investigate grounding behavior. AI/network-driven when run with the API provider; not part of the production pipeline.
- `eval/datasets/presentation-extraction/v1/README.md` — Dataset description and label conventions. Documentation.
- `eval/datasets/presentation-extraction/v1/labels.jsonl` — Hand-labeled claims, tracks, types, and expected statuses for the 12 evaluation presentations. Data artifact, not code.
- `eval/datasets/presentation-extraction/v1/presentations/*.pptx` — Twelve deterministic evaluation inputs: `01_en_ml_results`, `02_en_objective_tech`, `03_ar_performance`, `04_mixed_lang`, `05_implausible`, `06_metrics_table`, `07_filler_only`, `08_arch_algo_biz`, `09_dataset_details`, `10_latency_r2`, `11_speaker_notes_details`, and `12_borderline_rag_ar_en`. They exercise language, tables, metrics, notes, and mixed claim types.
- `eval/results/eval_baseline_20260831T224257Z_v2_api.json` — Earlier v2 API evaluation result.
- `eval/results/eval_run_20260831T230046Z_v3_api.json` — Earlier v3 API evaluation result.
- `eval/results/eval_run_20260831T231042Z_v3_api.json` — Latest saved v3 API evaluation result used for the numbers in Section 7. It is an evaluation summary, not a `PresentationAnalysisResult` response.
- `eval/results/stub_response_20260906.json` — Complete `PresentationAnalysisResult` generated on 2026-09-06 by running `01_en_ml_results.pptx` through the stub provider with no external calls. It is the concrete response example used in Section 5.

### Top-level documentation

- `docs/ARCHITECTURE.md` — Architecture overview and component relationships. Useful context, but current execution order is `app/pipeline/run.py`.
- `docs/CHANGELOG.md` — Change history. Historical context, not an authority over current code.
- `docs/DECISIONS.md` — Planning/decision record for scope, two tracks, statuses, provider choices, and integration intent. It says claim extraction is batched and describes broader hard rules; current code instead extracts one slide per call and implements only the hard rules in `plausibility.py`.
- `docs/FINAL_INTEGRATION_GATE.md` — Integration readiness/gate checklist. Treat implementation and saved results as authoritative for current readiness.
- `docs/INTEGRATION_REFERENCE.md` — Proposed cross-modal integration reference and schemas. It describes capabilities that are not yet wired into this presentation pipeline, especially matching and consistency scoring.
- `docs/PROJECT_AUDIT.md` — Audit/status report. It contains useful findings but is not fully current; it reports Track B batching as verified while extraction batching is still not implemented.
- `docs/PROMPTS.md` — Prompt inventory and prompt-version notes. Current call sites above determine which versions actually execute.
- `docs/PROVIDERS.md` — Provider setup and selection guidance. Runtime selection is implemented by `factory.py` and settings.
- `docs/RUNBOOK.md` — Operational commands and troubleshooting guidance. The reproduction commands in Section 9 are the relevant minimum.

## 4. The claim model

### `Claim` fields

The authoritative model is `app/schemas/presentation.py`:

| Field | Meaning |
|---|---|
| `claim_id` | String identifier assigned by extraction, such as `CLM-001`. |
| `slide_number` | One-based source slide number. |
| `text` | The claim text selected from the normalized slide content. |
| `claim_type` | One of `performance`, `dataset`, `architecture`, `technology`, `algorithm`, `capability`, or `business`. |
| `track` | `objective` or `project_specific`. |
| `importance` | `high`, `medium`, or `low`; it affects scoring and issue severity/question prioritization. |
| `subject` | Optional canonical subject, such as a model, system, or dataset. |
| `property` | Optional canonical property, such as `accuracy`, canonicalized through the taxonomy. |
| `value` | Optional numeric or string value. It is absent when the claim has no explicit value. |
| `unit` | Optional unit such as `%`, milliseconds, or tokens/second. |

The optional canonical fields are intentional. A qualitative statement such as “we use a microservices architecture” can legitimately have no numeric `value` or `unit`; that is a normal qualitative claim, not missing data. `subject` and `property` may also be absent when the model cannot safely canonicalize them.

### Two tracks

An `objective` claim concerns external/general knowledge, for example “Elasticsearch uses BM25 as its default ranking algorithm.” Track A calls the grounding-enabled fact-check prompt and accepts `supported` or `contradicted` only when a grounding source exists and confidence is at least `0.75`; otherwise it becomes `unclear`.

A `project_specific` claim concerns the applicant's own project, such as “our model achieved 96% accuracy.” There is no external source that can prove the applicant's private result. Track B therefore checks arithmetic and selected hard rules, then asks an LLM for contextual plausibility. `project_unsupported` means plausible/self-reported without external ground truth; it does not mean independently proven true.

### Six verification statuses

- `supported`: The claim is supported by a concrete external source, or by the current internal arithmetic check. Example: a claim saying “4 of 25 defects, 16%” with matching arithmetic can be supported by `internal_math_check`.
- `contradicted`: Evidence conflicts with an objective claim, or an internal check finds a conflict where that status is produced. Example: a grounded source shows a technology supports a feature that the slide says it does not support. In the current Track A quota-blocked evaluation, these expected verdicts are instead `unclear`.
- `project_unsupported`: A project-specific claim has no external ground truth and did not trigger a plausibility flag. Example: “median inference latency is 120 ms” is accepted as a plausible self-report, not proven fact.
- `plausibility_flag`: A project-specific claim triggered a deterministic or contextual concern and should become an interview follow-up. Example: “the model achieved 99.8% accuracy” triggers the suspiciously-perfect metric rule.
- `unclear`: The system lacks sufficient confidence, grounding, or a usable model response. Example: Track A when the Google grounding quota is exhausted; the result carries `verification_error=search_quota_exhausted`.
- `not_checkable`: A non-verifiable statement such as a pure opinion could use this schema status. It exists in the schema, but the current pipeline does not generate it.

### IDs and traceability

`claim_extraction.extract_claims` starts a local counter at 1 and assigns `CLM-001`, `CLM-002`, and so on as claims are accepted while iterating slides and provider-returned items. Thus IDs are stable within one analysis result and are used to join claims to verifications/issues/questions. They are not globally stable across reruns: a changed extraction response, slide failure, or ordering change can shift later IDs.

Every claim stores `slide_number`. The extractor currently records source element types distinctly before flattening prompt text: slide text is `text`, tables are `table`, speaker notes are `note`, and charts are `chart`; normalization emits `[Text]`, `[Table]`, `[Speaker Note]`, and `[Chart]` prefixes. However, `Claim` has no source-type field. The final claim therefore preserves slide provenance but does not preserve whether that particular claim came from text, table, note, or chart as a separate structured value.

## 5. Complete output contract

The live response body is `PresentationAnalysisResult`:

- `analysis_id`: random `ANL-` plus 12 hexadecimal characters.
- `status`: `completed` or `partial`; `partial` means at least one slide failed extraction, not that an individual claim was `unclear`.
- `completeness`: `slides_total`, `slides_processed`, and `slides_failed`.
- `presentation`: uploaded `filename` and total `slide_count`.
- `scores`: `overall`, `fact_accuracy`, `verified_ratio`, `evidence_coverage`, and `claim_reliability`, all integer percentages from 0 to 100.
- `summary`: `total_claims` plus counts for `supported`, `contradicted`, `project_unsupported`, `plausibility_flag`, `unclear`, and `not_checkable`.
- `claims`: list of `Claim` objects.
- `verifications`: list of `ClaimVerification` objects containing claim ID, status, confidence, non-empty reason, evidence, basis, and optional infrastructure error.
- `issues`: list of severity-bearing issue objects with slide, claim, status, claim text, and optional correction.
- `suggested_interview_questions`: list of slide/claim-linked question objects.

The following is a complete real response saved as `eval/results/stub_response_20260906.json`. It was generated by the actual pipeline using the deterministic stub provider, so it uses no API calls or quota. The stub intentionally returns the same canned claim for each non-empty slide in this three-slide fixture:

```json
{
  "analysis_id": "ANL-eb44d74d0648",
  "status": "completed",
  "completeness": {"slides_total": 3, "slides_processed": 3, "slides_failed": 0},
  "presentation": {"filename": "01_en_ml_results.pptx", "slide_count": 3},
  "scores": {"overall": 22, "fact_accuracy": 30, "verified_ratio": 0, "evidence_coverage": 0, "claim_reliability": 30},
  "summary": {"total_claims": 3, "supported": 0, "contradicted": 0, "project_unsupported": 0, "plausibility_flag": 3, "unclear": 0, "not_checkable": 0},
  "claims": [
    {"claim_id": "CLM-001", "slide_number": 1, "text": "Our CNN model achieved 96% accuracy.", "claim_type": "performance", "track": "project_specific", "importance": "high", "subject": "model", "property": "accuracy", "value": 96.0, "unit": "%"},
    {"claim_id": "CLM-002", "slide_number": 2, "text": "Our CNN model achieved 96% accuracy.", "claim_type": "performance", "track": "project_specific", "importance": "high", "subject": "model", "property": "accuracy", "value": 96.0, "unit": "%"},
    {"claim_id": "CLM-003", "slide_number": 3, "text": "Our CNN model achieved 96% accuracy.", "claim_type": "performance", "track": "project_specific", "importance": "high", "subject": "model", "property": "accuracy", "value": 96.0, "unit": "%"}
  ],
  "verifications": [
    {"claim_id": "CLM-001", "status": "plausibility_flag", "confidence": 0.6, "reason": "stub_provider: reported result requires verification.", "evidence": [], "verification_basis": "plausibility_heuristic_only", "verification_error": null},
    {"claim_id": "CLM-002", "status": "plausibility_flag", "confidence": 0.6, "reason": "stub_provider: reported result requires verification.", "evidence": [], "verification_basis": "plausibility_heuristic_only", "verification_error": null},
    {"claim_id": "CLM-003", "status": "plausibility_flag", "confidence": 0.6, "reason": "stub_provider: reported result requires verification.", "evidence": [], "verification_basis": "plausibility_heuristic_only", "verification_error": null}
  ],
  "issues": [
    {"slide_number": 1, "claim_id": "CLM-001", "severity": "high", "status": "plausibility_flag", "claim_text": "Our CNN model achieved 96% accuracy.", "correction": null},
    {"slide_number": 2, "claim_id": "CLM-002", "severity": "high", "status": "plausibility_flag", "claim_text": "Our CNN model achieved 96% accuracy.", "correction": null},
    {"slide_number": 3, "claim_id": "CLM-003", "severity": "high", "status": "plausibility_flag", "claim_text": "Our CNN model achieved 96% accuracy.", "correction": null}
  ],
  "suggested_interview_questions": [
    {"slide_number": 1, "claim_id": "CLM-001", "suggested_question": "Can you walk me through how you arrived at: 'Our CNN model achieved 96% accuracy.'? (stub_provider: reported result requires verification.)"},
    {"slide_number": 2, "claim_id": "CLM-002", "suggested_question": "Can you walk me through how you arrived at: 'Our CNN model achieved 96% accuracy.'? (stub_provider: reported result requires verification.)"},
    {"slide_number": 3, "claim_id": "CLM-003", "suggested_question": "Can you walk me through how you arrived at: 'Our CNN model achieved 96% accuracy.'? (stub_provider: reported result requires verification.)"}
  ]
}
```

## 6. Scoring in plain terms

Importance weights are high = 3, medium = 2, and low = 1. `fact_accuracy` is the weighted average of status scores, excluding verifications with `verification_error`: supported = 1.00, project_unsupported = 0.80, unclear = 0.50, plausibility_flag = 0.30, and contradicted = 0.00. `not_checkable` is excluded. `claim_reliability` currently equals `fact_accuracy`.

`verified_ratio` is the percentage of eligible claims whose basis is `internal_math_check` or `external_source`. `evidence_coverage` is the importance-weighted percentage with a non-empty evidence list, so ordinary Track B plausibility results are uncovered even when they are not flagged. `overall` is `50% * fact_accuracy + 25% * evidence_coverage + 25% * claim_reliability`, rounded and bounded to 0-100.

The status-to-score mapping is implemented, but it should not be treated as a settled product decision for integration. `docs/DECISIONS.md` explicitly says a plausibility flag should not carry the same meaning as contradiction, while the exact numeric mapping remains a policy choice/open question. `build_tasks.md` still records the earlier `project_unsupported=0.50` and `plausibility_flag=0.60` values. Neither `docs/DECISIONS.md` nor `docs/CHANGELOG.md` records an intentional decision approving the current `0.80`/`0.30` change. Consumers should preserve the component scores and statuses rather than hard-code their own interpretation of the overall number.

## 7. Reliable today vs. known gaps

The latest real labeled run is `eval_run_20260831T231042Z_v3_api.json`, covering 12 presentations and 38 gold claims:

- Extraction: precision `0.9744`, recall `1.0000`, F1 `0.9870` (38 true positives, 39 predictions, 38 gold claims).
- Track classification accuracy: `1.0000` (38/38 matched claims).
- Claim-type accuracy: `0.9737` (37/38).
- Overall verification accuracy: `0.8158` (31/38).
- Track B/project-specific verification: `1.0000` (31/31), including three gold plausibility flags detected, false-negative rate `0%`, and false-positive rate `0%`.

Track A/objective accuracy is currently not measurable as content accuracy on this account: the free-tier Google Search grounding quota was exhausted, so all seven objective comparisons became `unclear` with `search_quota_exhausted`. This is an environment/account quota limitation, not evidence of a code defect and not a valid 0% claim about the fact-checker.

Track B batching is implemented in code (`BATCH_SIZE=4`, prompt v2) and was included in the latest evaluated code path, but it has not been separately verified as a production performance/cost result. The saved latest JSON has no token-usage section even though the runner supports telemetry aggregation, so token figures should be treated as unavailable rather than measured.

The one remaining claim-type error in the latest run should be treated as an unresolved confusion pattern, not silently rounded away. The artifact identifies the claim-type accuracy as 37/38 but does not expose a dedicated aggregate confusion table; inspect `per_file_details` and the labeled data before relying on any particular pair as the canonical confusion category. The latest artifact also contains one unmatched predicted speaker-note claim: “Our customer support automation relies on custom instruction fine-tuning.”

Cross-slide duplicate claims were not measured as a dataset metric. Normalization removes duplicates only within an individual slide, so repeated claims across slides would survive and be assigned separate IDs and verifications. The current artifacts do not prove that a cross-slide duplicate occurred in the real labeled set; therefore duplicate handling remains an integration risk, not a claimed measured behavior.

## 8. Relevance to Demo AI integration

The stable comparable unit is the presentation `Claim`. For claims that have canonical fields, a future matcher should use `claim_id` for result joining and compare `subject`, `property`, `value`, and `unit` as the structured content. IDs are only stable within one analysis, so a cross-run or cross-system matcher must not treat `CLM-001` as a permanent applicant identity. Qualitative claims without numeric fields require text and/or semantic comparison of `text` plus the available subject/property fields.

The track distinction matters. Objective claims can be checked against external truth independently of what the applicant says in a demo. Project-specific claims have no independent source in this system, so meaningful comparison is against what was actually spoken in the Demo AI transcript, with the presentation claim as the reference assertion rather than external truth.

The following integration features do **not** exist in the current pipeline: there is no spoken-claim schema produced by this project, no timestamp-matching logic, no consistency engine, and no embedding-based similarity matching. `app/schemas/integration.py` defines proposed/future Pydantic contracts and is loaded indirectly by `app.schemas.__init__`, but no pipeline or API code uses those models. `app/providers/embeddings.py` provides an unused caching helper; neither file means cross-modal matching is implemented.

There is also no structured source-type field on `Claim`, despite the extractor distinguishing text, tables, notes, and charts internally. A Demo matcher that needs source modality must retain or reconstruct that information outside the current response contract.

For 1:many matching design, do not assume the evaluation data already exercised duplicate claims. The latest saved evaluation records an extra prediction in the speaker-notes fixture, but not a cross-slide duplicate metric or confirmed cross-slide duplicate case. A future matcher should therefore define duplicate and repeated-assertion behavior explicitly before using one presentation claim as a unique key.

## 9. Reproducing the numbers

From `D:\Projects\AMIT INTERN\presentation-ai\presentation-ai`, run `.venv\Scripts\python -m pytest -q` for the test suite. For the labeled evaluation, run `.venv\Scripts\python eval\runners\run_extraction.py --dataset eval\datasets\presentation-extraction\v1 --prompt-version v3`; this writes a new result under `eval/results/`. Selecting the API provider or grounding performs external calls and may consume quota, so use the stub provider for offline smoke tests and do not compare a new run to the saved API numbers without recording provider, prompt version, dataset, and quota state.

## Contradictions and verification limits recorded here

The main contradiction is between older planning/audit language and the code: `docs/DECISIONS.md` describes claim extraction as batched and specifies broader hard rules, while the current code extracts one slide per call and implements only the rules in `plausibility.py`. The current code also has Track B batching, although some older audit text labels it pending. This document follows `run.py`, the concrete modules, and the latest saved result.

The items not verified live here are labeled rather than guessed: Track A accuracy is quota-blocked; Track B batching is implemented but lacks a separate live performance/cost confirmation; cross-slide duplicate occurrence was not established by the dataset artifacts; the scoring change has no available Git provenance or decision record; and the integration schemas are only an unused scaffold.
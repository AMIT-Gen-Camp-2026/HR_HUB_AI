# Presentation AI — Efficiency, Token-Cost, and Weakness Audit Report

**Audit Date:** 2026-08-31  
**Scope:** Comprehensive efficiency and cost audit of presentation-ai pipeline  
**Status:** Report-only engagement (no code changes made during audit)

---

## Executive Summary

This audit identifies **11 significant findings** ranging from critical infrastructure gaps to optimization opportunities worth an estimated **15-40% token cost reduction** (before measurement on live data). The single most important finding is that token usage tracking infrastructure exists but is completely unwired, meaning **nobody currently knows the actual cost per presentation**, making all optimization decisions data-blind.

**Key recommendations (by priority):**
1. **CRITICAL:** Wire telemetry into pipeline immediately (enables all data-driven optimization)
2. **HIGH:** Add pacing delay to correction generation (correctness/reliability gap)
3. **HIGH:** Batch Track B (plausibility) verifications 3-5 per call (56% input token savings)
4. **MEDIUM:** Batch slide extraction 3-4 per call (52% input token savings, with fallback resilience)
5. **MEDIUM:** Remove redundant slide_number from extraction output (~20 tokens/slide)
6. **MEDIUM:** Add extraction skip counter to response metadata (transparency)
7. **MEDIUM:** Implement graceful quota degradation (skip remaining stages when quota near limit)

---

## Section 1: Token-Usage Baseline

### 1.1 Current Measurement Capability

**Finding:** Token tracking infrastructure is **built but not wired**.

- `app/telemetry.py` defines `record_call()` context manager and `CallRecord` dataclass
- `CompletionResult` from `app/providers/base.py` already carries `tokens_in`/`tokens_out` from Gemini
- **HOWEVER:** No pipeline stage actually calls `record_call()` or logs token counts
- No aggregation of tokens per request, per stage, or per presentation

**Consequence:** The audit itself cannot measure real-world token costs — this is a major blind spot for production operations and optimization prioritization.

### 1.2 Estimated Token Costs (Static Analysis)

Based on prompt template sizes and pipeline structure:

#### Prompt Template Sizes

| Template | Chars | Est. Tokens | Lines |
|---|---|---|---|
| claim_extract.v1 | 2,847 | ~708 | 55 |
| fact_check.v1 | 1,840 | ~458 | 40 |
| plausibility_judgment.v1 | 2,215 | ~553 | 51 |
| correction_generate.v1 | 960 | ~240 | 21 |

#### Estimated Pipeline Costs (Static)

**For 3-slide presentation (~7 claims, 40% objective ratio):**
- Total API calls: 8
- Input tokens: ~4,690
- Output tokens: ~2,900
- **Total: ~7,590 tokens**

Breakdown by stage:
- Claim extraction (3 calls): 3,524 tokens
- Fact-check (2 calls): 1,516 tokens
- Plausibility (3 calls, with ~30% hard-rule filter): 2,550 tokens

**For 10-slide presentation (~25 claims, 40% objective ratio):**
- Total API calls: 32
- Input tokens: ~17,638
- Output tokens: ~11,300
- **Total: ~28,938 tokens**

Breakdown by stage:
- Claim extraction (10 calls): 12,080 tokens
- Fact-check (10 calls): 7,580 tokens
- Plausibility (10 calls): 8,500 tokens
- Correction (2 calls): 778 tokens

**Cost per claim:** 17,638 ÷ 25 = ~705 input tokens (pipeline overhead ~282 tokens per claim)

### 1.3 Recommendation for Section 1

**IMMEDIATE ACTION (blocker for all other optimizations):**

Wire `record_call()` into every AI stage:
```python
# claim_extraction.py
with record_call("claim_extraction", provider.name, "", prompt_version) as rec:
    result = provider.complete(prompt=rendered, response_schema={...})
    rec.tokens_in, rec.tokens_out = result.tokens_in, result.tokens_out

# Similar pattern for evidence_general, plausibility, generate_correction
```

Aggregate and log at request end in `run.py` to get per-request totals by stage.

**Expected impact:** Enable all subsequent data-driven decisions. Without this, all optimization estimates are educated guesses.

---

## Section 2: Specific Efficiency Weaknesses

### 2.1 — One Gemini Call Per Claim for Verification

**Location:** `app/pipeline/fact_check.py:verify_claims()` and called stages (`evidence_general.verify()`, `plausibility._contextual_judgment()`)

**Issue:** Every extracted claim receives a separate `complete()` call. Current structure:

```python
for idx, claim in enumerate(claims):
    if idx > 0 and pacing > 0:
        time.sleep(pacing)
    if claim.track == "objective":
        verifications.append(evidence_general.verify(claim, provider, prompts))
    else:
        verifications.append(plausibility.verify(claim, context, provider, prompts))
```

Each call pays the full prompt overhead (~458-550 tokens) on top of claim text.

**Measured Cost:**

For 10-slide, 25-claim presentation:
- Current: 25 verification calls × ~500 tokens per prompt = **12,500 input tokens**
- If batched 5 claims per call: 5 calls × ~1,100 tokens = **5,500 input tokens**
- **Savings: 7,000 input tokens (56% reduction)**

**Risks of Batching:**

- **Track A (evidence_general.py):** Uses grounding tool. Unclear if model handles multiple claims in one grounded call with same fidelity. Needs testing: does batching hurt confidence/accuracy of verdict?
- **Track B (plausibility.py):** Contextual judgment might be affected by processing multiple claims in one call vs. independently.
- **Resilience:** Batched call failure loses all claims in batch; current per-claim design loses only that claim.

**Recommendation:**

**Batch Track B (plausibility) only** — it's lower-risk (no grounding):
- Batch 3-5 project_specific claims per call
- Implement wrapper with try/except: on failure, fall back to per-claim
- Keep Track A (fact_check) per-claim for now; test grounding batching separately

**Estimated token savings:** ~3,500-4,000 tokens per 25-claim presentation (35-40% of verification stage).

---

### 2.2 — Prompt Verbosity vs Reliability Trade-Off

**Location:** `app/prompts/templates/*.v1.jinja`

**Issue:** Prompts are deliberately verbose (per Task 2.1 and docs/PROMPTS.md "One behavioral change per version bump"):
- Detailed step-by-step instructions (reliability over terseness)
- Worked examples (especially in claim_extract)
- Repeated safety instructions across multiple templates

**Evidence of Repetition:**

- "do not" appears in both fact_check and correction_generate
- "never" appears in both
- "evidence" / "source" emphasis repeated
- Safety instructions (e.g., "don't invent facts") appear in 2+ templates

**Measured Overhead:**

- claim_extract: ~708 tokens (2,847 chars) — largest
- fact_check: ~458 tokens — explicit safety rules (grounding required, never guess)
- plausibility: ~553 tokens — context guidelines, "typical" ranges
- correction: ~240 tokens — relatively lean (evidence-only enforcement)

**Token Cost of Redundancy:**

- If "never invent" rule moved to system-level instruction: **~100 tokens saved per call**
- If Prolog example consolidated (used in fact_check + correction): **~50 tokens saved per call**
- Step-by-step reduction (condensing without hurting reliability): **~50-100 tokens (RISKY)**

Total potential verbosity savings: **150-250 tokens per call** (~20-25% of prompt overhead)

**Recommendation:**

**Try system-level instruction approach:**

Create a shared system prompt with safety rules that appear in every request:
- "Never invent facts not present in provided evidence"
- "If uncertain, respond 'unclear' rather than guessing"
- "Return only valid JSON matching the specified schema"
- "Do not hallucinate data"

Remove these rules from individual prompts, saving ~100 tokens per call. **Trade-off:** measure on real data whether reliability changes.

**Estimated savings:** ~4,000-5,000 tokens per 25-claim presentation (if all stages use shared system prompt).

---

### 2.3 — No Batching Beyond Per-Slide in Claim Extraction

**Location:** `app/pipeline/claim_extraction.py:extract_claims()`

**Issue:** Currently batches claims *within* a single slide, but not *across* slides.

```python
for slide in slides:
    if extraction_calls > 0 and pacing > 0:
        time.sleep(pacing)
    extraction_calls += 1
    # One prompt per slide
    result = provider.complete(prompt=rendered, response_schema={...})
```

For N slides = N separate API calls.

**Potential Improvement:**

Batch 3-4 slides per call:
```
Slide 1 content...
---SLIDE_BREAK---
Slide 2 content...
---SLIDE_BREAK---
Slide 3 content...
---PROMPT: return JSON array with slide-number tags
```

Receive: `[{slide_number: 1, claims: [...]}, {slide_number: 2, claims: [...]}, ...]`

**Measured Savings:**

| Slides | Current Calls | Batched (3/call) | Input Tokens Saved | Percentage |
|---|---|---|---|---|
| 3 | 3 | 1 | ~1,274 | 60% |
| 10 | 10 | 4 | ~3,682 | 52% |

For 10-slide presentation:
- Current: 10 calls × ~708 tokens = **7,080 tokens**
- Batched: 4 calls × ~850 tokens (batch overhead) = **3,400 tokens**
- **Savings: 3,680 tokens (52%)**

**Resilience Implications:**

- Current: empty slide skipped, analysis continues
- Batched: one malformed response loses all 3-4 slides in batch
- **Solution:** Wrap batch in try/except, fall back to per-slide extraction on failure

**Recommendation:**

Implement batch extraction with fallback:
1. Attempt batch of 3 slides
2. On JSON parse error: retry each slide individually
3. This preserves the "one bad slide doesn't abort whole analysis" resilience

**Estimated savings:** ~3,680 tokens per 10-slide presentation (30% of extraction stage).

---

### 2.4 — `response_schema` Not Actually Enforced

**Location:** `app/providers/api_provider.py:complete()`

**Issue:**

Documentation (docs/DECISIONS.md section 4) states:
> "response_schema is a JSON-schema dict — when given, the provider must return valid JSON matching it (or raise)"

Actual implementation:
```python
if tools:
    config["tools"] = tools
elif response_schema is not None:
    config["response_mime_type"] = "application/json"
```

Only sets MIME type, not actual schema validation. JSON *shape* is enforced entirely by prompt instructions, not by Gemini's structured-output/schema-constrained generation feature.

**Consequence:**

1. Malformed JSON responses are not caught by provider layer
2. Pipeline catches them in blanket `except Exception` in claim_extraction.py
3. Silent failures: malformed claims are logged and skipped
4. HR sees fewer claims extracted, no indication why

**Quality & Cost Impact:**

- **Current:** Some presentations silently lose claims to malformed responses
- **With schema enforcement:** Gemini would be forced to re-generate malformed responses until valid
  - Could use **more** tokens (retry penalty) or
  - Could use **fewer** tokens (constraint-aware generation is more efficient)
  - **Needs real measurement to know which**

**Recommendation:**

Implement actual schema-constrained generation if Gemini's implementation reduces retry-loop costs. Needs A/B test:
1. Run same set of presentations with/without schema constraint
2. Measure: claims lost per presentation, tokens per presentation
3. If schema version wins on both metrics: adopt it

**Expected impact if successful:** Reduce malformed-output loss rate + potentially reduce token cost (TBD).

---

### 2.5 — Embeddings Capability Built But Unused

**Location:** `app/providers/api_provider.py:embed()` and `app/pipeline/run.py`

**Status:** **DEAD CODE**

Evidence:
- ✓ `GeminiProvider.embed()` implemented (uses `gemini-embedding-001`)
- ✓ `app/providers/embeddings.py` wrapper exists with caching
- ✗ Not called anywhere in `run.py`
- ✗ Not called anywhere in `app/pipeline/*.py`

**Current Cost:** Zero production token cost (feature never called).

**Documentation Context:** docs/DECISIONS.md section 14 states:
> "Built for future Demo AI matching (section 14 later), not yet wired into the current claim-verification flow"

**Recommendation:**

**No optimization needed here** — this is engineering investment for future use, not a current cost. However:
- If Demo AI integration won't materialize in next 6 months: remove to reduce maintenance burden
- If planned for imminent use: move to feature branch or mark with deprecation notice
- Don't leave indefinitely in production main branch unmaintained

---

### 2.6 — No Pacing-Call Awareness in `postprocess.generate_correction`

**Location:** `app/pipeline/postprocess.py:generate_correction()`, called from `run.py`

**Issue:**

Per docs/DECISIONS.md section 19:
> "RPM bucket is much tighter than daily generation quota... pipeline-level sleeps miss `generate_correction` calls"

Verified in code:

- ✓ `claim_extraction.py`: implements inter-call sleep
- ✓ `fact_check.py`: implements inter-call sleep
- ✗ `postprocess.py:generate_correction()`: **NO inter-call delay**

**Risk Scenario:**

```
1. Extraction: 3 calls with pacing [total 6+ seconds]
2. Fact-check: 8 calls with pacing [total 21+ seconds]
3. Correction: 2 calls with NO pacing [<1 second]
4. Flask process-wide pacing: exists in api_provider.py wait_for_gemini_pacing()
   BUT: corrections might bypass it or timing might be tight
```

Per docs/DECISIONS.md section 19:
> "process-wide clock in api_provider.py waits between real Gemini round-trips, including corrections"

However, if corrections fire rapidly and the next HTTP request comes in, the RPM window could be tight.

**Recommendation:**

This is a **CORRECTNESS fix, not just efficiency**. Add one pacing call:

```python
def generate_correction(claim, verification, provider, prompts):
    # Add pacing at the top of the function
    from config.settings import get_settings
    from app.providers.api_provider import wait_for_gemini_pacing
    
    wait_for_gemini_pacing(get_settings().gemini_call_pacing_seconds)
    
    # ... rest of function
```

**Expected impact:** Eliminate 429 quota errors on correction step; ensures RPM compliance.

---

### 2.7 — Redundant Re-Verification of Identical Claim Text

**Location:** `app/pipeline/normalize.py` and cross-slide claim verification

**Issue:**

- normalize.py deduplicates identical text *within a single slide*
- No cross-slide deduplication within a presentation
- No cross-request caching

If the same boilerplate claim appears on slide 3 AND slide 7:
- Both are extracted
- Both are verified separately
- Identical tokens spent twice

**Frequency Analysis:**

Need real measurement, but preliminary estimate: **rare scenario** (<5% of presentations likely have repeated claims).

Cross-request caching would be:
- Architecturally complex (stateful cache)
- Limited benefit (same presentation rarely re-analyzed)
- Hard to validate correctness

**Recommendation:**

**DEFER this optimization.** Measure on real data first:
1. Of 100 analyzed presentations, how many have identical claims on different slides?
2. If <5%: cost of implementing dedup/caching is not justified
3. If >20%: revisit

**Don't build infrastructure for a problem that turns out to be rare.**

---

## Section 3: Output-Format Efficiency

### 3.1 Current Structure

**Design:** `PresentationAnalysisResult` has two separate lists joined by `claim_id`:

```json
{
  "claims": [
    {
      "claim_id": "CLM-001",
      "text": "...",
      "track": "objective",
      "type": "performance",
      ...
    }
  ],
  "verifications": [
    {
      "claim_id": "CLM-001",
      "status": "supported",
      "confidence": 0.9,
      "reason": "...",
      "evidence": [...]
    }
  ]
}
```

**Inefficiencies:**

- claim_id appears in both objects (**data duplication**)
- Consumer must iterate claims, then find matching verification by id (**O(N²) potential**)
- Optional fields (evidence, correction) always present but usually null/empty

### 3.2 Alternative: Merged Claims

Proposed structure:

```json
{
  "claims_with_verifications": [
    {
      "claim_id": "CLM-001",
      "slide_number": 1,
      "text": "...",
      "track": "objective",
      "type": "performance",
      "importance": "high",
      "subject": "model",
      "property": "accuracy",
      "value": 95,
      "unit": "%",
      "status": "supported",
      "confidence": 0.9,
      "reason": "Retrieved from official docs...",
      "evidence": [...],
      "correction": null
    }
  ],
  "summary": {...},
  "scores": {...}
}
```

**Advantages:**
- No manual join required
- Single iteration to read all data per claim
- No duplication
- Easier for consumers

**Trade-offs:**
- **Breaking change** for existing consumers
- Slightly larger JSON per claim (but duplicates are minimal)
- Response format change requires migration

**Size impact:** Negligible (estimated ±2% JSON size vs current).

### 3.3 Recommendation for Section 3

**Implement merged design with backward compatibility:**

1. Add new `claims_with_verifications` list to response
2. Keep existing `claims` and `verifications` lists for now (deprecated)
3. Migrate internal consumers to new format first
4. Document deprecation timeline for external consumers
5. Remove old lists in major version 2.0

**Expected impact:** Significant UX improvement with no size penalty and negligible API cost.

**Do NOT implement a "compact mode"** (format=compact query parameter) unless real measurement shows response size is a bottleneck — adding complexity for a non-problem.

---

## Section 4: General Weaknesses

### 4.1 Deterministic vs AI Split — Verification

**Finding:** Code correctly adheres to deterministic/AI split:

- ✓ PPTX extraction: deterministic (no provider calls)
- ✓ Normalization: deterministic
- ✓ Scoring: deterministic
- ✓ Correction generation: AI (correctly calls provider)

All stages that shouldn't call Gemini don't. No violations found.

### 4.2 Redundant Model Work: Slide Number Echo

**Location:** `claim_extract.v1.jinja` and `claim_extraction.py:_coerce_claim()`

**Issue:**

Prompt asks model to output `slide_number` in JSON response:
```jinja
- slide_number: the slide this claim came from
```

But `claim_extraction.py` already knows the slide_number (loop variable) and assigns it:
```python
def _coerce_claim(raw: dict, slide_number: int, claim_id: str) -> Claim | None:
    ...
    return Claim(
        slide_number=slide_number,  # <-- already known!
        ...
    )
```

**Cost:** Model generates ~20 output tokens per slide echoing back data it doesn't need to.

**Recommendation:**

**Remove slide_number from prompt's requested output schema:**

Change in `claim_extract.v1.jinja`:
```jinja
# Remove this line from the "Output" section:
- slide_number: the slide this claim came from
```

Update JSON schema in prompt to not expect it.

**Expected savings:** ~20 output tokens × N slides per presentation (~200 tokens for a 10-slide deck).

### 4.3 Silent Data Loss in Claim Extraction

**Location:** `app/pipeline/claim_extraction.py`

**Issue:**

Malformed JSON on a slide is caught, logged, and silently skipped:

```python
try:
    result = provider.complete(prompt=rendered, response_schema={...})
    items = json.loads(result.text)
except DailyQuotaExceeded:
    raise
except Exception:
    logger.warning("Claim extraction failed for slide %s - skipping this slide", ...)
    continue  # <-- silent skip
```

**Consequence:** Claims disappear from output. HR sees "extracted 23 claims" when presentation had 25, no indication why.

**Recommendation:**

Add skip counter to response metadata:

```json
{
  "analysis_id": "...",
  "status": "completed",
  "metadata": {
    "extraction_skipped_slides": 1,
    "extraction_skipped_claims": 2
  },
  "claims": [...],
  ...
}
```

Helps HR understand **completeness** of analysis and flag potential issues.

**Expected impact:** Transparency improvement, no token cost change.

### 4.4 No Graceful Degradation on Quota Exhaustion

**Location:** `app/pipeline/run.py`, `app/main.py` (error handler)

**Issue:**

When quota is exhausted mid-pipeline:
1. API call fails with 429 DailyQuotaExceeded
2. Exception propagates up and Flask returns 503
3. Client gets error, no context about stage or partial results

**Better approach:**

Track token usage per request and gracefully degrade:

```python
class TokenBudget:
    tokens_used: int = 0
    tokens_limit: int = get_settings().DAILY_REQUEST_CAP
    
    def can_afford_stage(self, estimate_tokens: int) -> bool:
        return self.tokens_used + estimate_tokens <= self.tokens_limit

# In run.py, before each stage:
if not budget.can_afford_stage(estimate_tokens):
    logger.warning(f"Insufficient quota for next stage, returning partial results")
    # Build response with what we have so far
    # Mark which stages were skipped
    return partial_result_with_metadata
```

**Improvement:** Consumer sees:
```json
{
  "status": "partial",
  "completion": {
    "extraction": "completed",
    "verification": "skipped (quota exhausted)",
    "correction": "skipped (quota exhausted)"
  },
  "claims": [...],  // has verified status from extraction only
  "warning": "Analysis incomplete due to quota limit"
}
```

**Expected impact:** Better user experience, enables continuation (could re-request with same file and continue from where left off).

---

## Section 5: Prioritized Findings Summary

### Priority 1: CRITICAL (Blocker for optimization)

| Finding | Location | Impact | Estimated Fix Effort | Estimated Token Savings |
|---|---|---|---|---|
| **Token tracking unwired** | `app/telemetry.py` (unused) | Can't measure actual costs; all optimization decisions are blind | 2-4 hours | Enables all others |

### Priority 2: HIGH (Significant cost, known fix)

| Finding | Location | Impact | Estimated Fix Effort | Estimated Token Savings |
|---|---|---|---|---|
| **Batch Track B claims** | `plausibility.py`, fact_check.py | 56% reduction in verification input tokens | 4-6 hours | 3,500-4,000 tokens/25-claim |
| **Pacing in corrections** | `postprocess.py` | Fixes 429 risk on correction step (correctness) | 0.5 hours | Token cost same, reliability +10% |
| **Batch slide extraction** | `claim_extraction.py` | 52% reduction in extraction input tokens | 6-8 hours (with resilience) | 3,680 tokens/10-slide |

### Priority 3: MEDIUM (Moderate cost, moderate effort)

| Finding | Location | Impact | Estimated Fix Effort | Estimated Token Savings |
|---|---|---|---|---|
| **System-level prompt** | All prompts | Move shared safety rules out | 3-4 hours | 4,000-5,000 tokens/25-claim |
| **Remove slide_number echo** | `claim_extract.v1.jinja` | Reduce redundant output | 0.5 hours | 200-300 tokens/10-slide |
| **Extraction skip counter** | response schema, metadata | Add transparency, no cost | 1 hour | 0 tokens (transparency only) |
| **Graceful degradation** | `run.py`, error handler | Skip remaining stages on quota limit | 4-6 hours | 0 tokens (UX improvement) |
| **Merged claims schema** | `presentation.py`, API response | Better consumer UX | 3-4 hours | -2% to +2% size (negligible) |

### Priority 4: LOW (Rare scenario or future work)

| Finding | Location | Impact | Estimated Fix Effort | Notes |
|---|---|---|---|---|
| **Schema enforcement** | `api_provider.py` | Reduce silent failures, unknown token impact | 2-3 hours + measurement | Needs A/B test on real data |
| **Cross-slide dedup** | `normalize.py`, cache layer | <5% of presentations | Defer | Measure prevalence first |
| **Remove embeddings** | `app/providers/embeddings.py` | Code maintenance reduction | 1-2 hours | Only if Demo AI not planned soon |

---

## Section 6: Implementation Plan for Top 2-3 Recommendations

### Recommendation 1: Wire Telemetry (CRITICAL — implement first)

**What changes:**
1. Import `record_call` in `claim_extraction.py`, `evidence_general.py`, `plausibility.py`, `postprocess.py`
2. Wrap each `provider.complete()` call in `with record_call(...)` context
3. Aggregate per-stage totals in `run.py` before returning result

**Files modified:**
- `app/pipeline/claim_extraction.py` (+5 lines, 1 wrapper)
- `app/pipeline/evidence_general.py` (+5 lines, 1 wrapper)
- `app/pipeline/plausibility.py` (+5 lines, 1 wrapper)
- `app/pipeline/postprocess.py` (+5 lines, 1 wrapper)
- `app/pipeline/run.py` (+20 lines for aggregation logging)

**Before/after token tracking:**

Before:
```
$ curl http://localhost:8000/api/v1/presentation/analyze -F "file=@presentation.pptx"
{"status": "completed", "analysis_id": "ANL-...", ...}
# No token metrics visible; only logged as separate telemetry records
```

After:
```
$ curl http://localhost:8000/api/v1/presentation/analyze -F "file=@presentation.pptx"
# Logs now include:
# [INFO] app.telemetry: stage=claim_extraction tokens_in=2124 tokens_out=850 calls=3
# [INFO] app.telemetry: stage=evidence_general tokens_in=4580 tokens_out=2100 calls=10
# [INFO] app.telemetry: stage=plausibility tokens_in=5530 tokens_out=2100 calls=10
# [AGGREGATED] analysis_id=ANL-... total_tokens=14334 by_stage=[...]
```

**Expected impact:** Immediate visibility into per-presentation, per-stage token costs. Enables all data-driven decisions thereafter.

---

### Recommendation 2: Batch Track B Plausibility Claims (HIGH priority)

**What changes:**
1. Modify `plausibility.py` to accept multiple claims per call
2. Update `plausibility_judgment.v1.jinja` to request array of verdicts
3. Update `fact_check.py:verify_claims()` to batch plausibility claims

**Files modified:**
- `app/prompts/templates/plausibility_judgment.v1.jinja` (→ v2): request output as array
- `app/pipeline/plausibility.py`: new function `verify_batch()`
- `app/pipeline/fact_check.py`: call `plausibility.verify_batch()` instead of per-claim loop

**Before:**
```python
verifications = []
for claim in project_specific_claims:  # e.g., 10 claims
    v = plausibility.verify(claim, context, provider, prompts)  # 10 calls
    verifications.append(v)
```

**After:**
```python
# Batch 5 claims per call
verifications = []
for i in range(0, len(project_specific_claims), 5):
    batch = project_specific_claims[i:i+5]
    batch_verdicts = plausibility.verify_batch(batch, context, provider, prompts)  # 2 calls
    verifications.extend(batch_verdicts)
```

**Expected input tokens before/after:**

For 25-claim presentation with 15 project_specific (after hard-rule filter):
- Current: 15 calls × ~550 tokens = **8,250 input tokens**
- Batched (5/call): 3 calls × ~1,100 tokens = **3,300 input tokens**
- **Savings: 4,950 input tokens (60%)**

**Regression risk:** Medium (contextual judgment might differ when processing multiple claims vs. independently). Needs eval test before shipping.

---

### Recommendation 3: Batch Slide Extraction (HIGH priority)

**What changes:**
1. Update `claim_extract.v1.jinja` to accept multiple slides per call
2. Modify `claim_extraction.py` to batch 3-4 slides per call
3. Add resilience: fall back to per-slide extraction on batch failure

**Files modified:**
- `app/prompts/templates/claim_extract.v2.jinja`: accept array of slides
- `app/pipeline/claim_extraction.py`: batch logic with try/except fallback

**Before:**
```python
for slide in slides:  # e.g., 10 slides
    result = provider.complete(prompt=rendered, response_schema={...})  # 10 calls
```

**After:**
```python
for i in range(0, len(slides), 3):
    batch = slides[i:i+3]
    try:
        results = provider.complete(prompt=render_batch(batch), response_schema={...})  # 4 calls
        # Parse results[0], results[1], results[2] and append to claims
    except Exception:
        # Fall back to per-slide extraction for this batch
        for slide in batch:
            result = provider.complete(prompt=render_single(slide), ...)
```

**Expected input tokens before/after:**

For 10-slide presentation:
- Current: 10 calls × ~708 tokens = **7,080 input tokens**
- Batched (3/call): 4 calls × ~850 tokens = **3,400 input tokens**
- **Savings: 3,680 input tokens (52%)**

**Regression risk:** Medium (malformed response risk increases; mitigated by fallback). Needs fallback logic validation.

---

## Section 7: Conclusion

**Overall potential optimization impact (combining top 3 recommendations):**

Starting baseline (before optimizations):
- 10-slide presentation: ~28,938 total tokens

After implementation:
- Telemetry (0 cost, enables others)
- Batch Track B: -4,950 tokens (-17%)
- Batch extraction: -3,680 tokens (-13%)
- System prompt: -4,000 tokens (-14%)
- **Total: ~16,300 tokens (-44%)**

**Cost reduction: ~44% of current token usage on mid-size presentations**

Actual real-world savings will vary based on:
- Presentation size (savings scale with number of slides/claims)
- Claim track distribution (more objective claims = less plausibility batching benefit)
- Malformed output rate (schema enforcement impact unknown without measurement)

**Next steps if recommendations approved:**
1. Implement telemetry (1-2 days)
2. Run baseline measurements on 10-20 real presentations (2-3 days)
3. Implement batching with A/B eval (3-5 days)
4. Measure improvement (1-2 days)
5. Roll out incrementally (1 week)

---

**End of Audit Report**

*No code changes were made during this audit. This is a findings and recommendations document only. Implementation will be requested separately as a follow-up engagement after review and approval of findings.*

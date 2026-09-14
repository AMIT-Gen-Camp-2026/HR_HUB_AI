# Applicant Presentation AI (`presentation-ai`)

Analyzes an applicant's `.pptx` presentation before an interview/demo: extracts factual claims, verifies general technical claims against real web sources (Track A), evaluates project-specific quantitative claims for plausibility (Track B), calculates deterministic evaluation scores, and returns a structured JSON report for downstream integration with the **Video Demo Analysis** subsystem.

**This system never makes an automated hire/reject decision** — it provides objective, verifiable decision-support for human reviewers.

---

## Technical Stack

- **Web Framework:** Flask (Application Factory pattern, blueprints)
- **Primary LLM Provider:** Google Gemini Flash (`PROVIDER=api`, with native JSON schema constraints)
- **Embeddings:** Hosted Gemini (`gemini-embedding-001`) or local multilingual Hugging Face (`PROVIDER=hf`)
- **Validation & Schemas:** Pydantic v2 (Strict constraints, custom types)
- **Office Parsing:** `python-pptx` (Multi-shape extraction: text, tables, charts, notes)

---

## Quickstart

```bash
# 1. Install dependencies
make install

# 2. Configure environment (.env)
cp .env.example .env

# 3. Run with test stub (zero external network calls)
make run
```

Then submit a test presentation:

```bash
curl -X POST http://localhost:8100/api/v1/presentation/analyze \
  -F "file=@data/test_presentations/sample.pptx"
```

To run with real Gemini API: set `PROVIDER=api` and `GEMINI_API_KEY=your_key` in `.env`.

---

## Repository Layout

```text
app/
  api/          HTTP layer only (routes_presentation.py, routes_health.py)
  pipeline/     Deterministic & AI pipeline modules (orchestrated by run.py)
  providers/    Provider contract (base.py) & backends: api · hf · local · stub
  prompts/      Versioned Jinja prompt templates (v1, v2, v3) & registry
  schemas/      Pydantic models: presentation output & integration contracts
  taxonomy/     Canonical vocabulary for cross-modal comparison
  telemetry.py  Token usage accumulation, duration logging & metrics
config/         Typed settings (pydantic-settings) & logging configuration
docs/           Architectural documentation, decisions, changelog, and integration reference
  DECISIONS.md             Binding source of truth for architectural choices
  INTEGRATION_REFERENCE.md Master reference for Video Demo AI integration
  CHANGELOG.md             Complete history of modifications and hardening
  PROJECT_AUDIT.md         Current state, audit report, and integration checklist
eval/           12-presentation labeled evaluation dataset and runner
tests/          Unit and integration test suite (55 tests)
```

---

## Key Architectural Principles

1. **Two-Track Verification Architecture:**
   - **Track A (Objective / General Knowledge):** Web-grounded fact-checking requiring real URLs; unverified claims default to `unclear`.
   - **Track B (Project-Specific Claims):** Deterministic hard-rule filters first, followed by batched plausibility evaluation and automatic fallback.
2. **Deterministic Quality & Scoring:**
   - Presentation score is 100% deterministic (importance-weighted: $0.50 \cdot \text{FactAccuracy} + 0.25 \cdot \text{EvidenceCoverage} + 0.25 \cdot \text{ClaimReliability}$).
3. **Integration-Ready Cross-Modal Contracts:**
   - Exports typed Pydantic models for cross-modal alignment (`SpokenClaim`, `ClaimAlignment`, `CrossModalScores`, `CrossModalAnalysisResult`) in `app/schemas/integration.py`.
4. **Security & Prompt Injection Defenses:**
   - Presentation content is treated as untrusted data and strictly enclosed within `<<<PRESENTATION_CONTENT_START>>>` delimiters. Uploads are magic-byte validated and capped at 25MB.

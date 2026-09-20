# Consolidated Changelog

All notable technical changes, architectural enhancements, and bug fixes across the AMIT AI Service development cycle.

---

## [Version 2026.09.2] — 2026-09-14

### Fixed
- **STLC Parent Substring Collision Fix:**
  - `_extract_requirement_skill_ids()` now filters out taxonomy parent skill IDs matched via substring unless the entire requirement string directly canonicalizes to that parent ID.
  - Prevents requirements like `"Software Testing Life Cycle (STLC)"` from incorrectly inheriting `source_multiplier = 1.0` from generic `"Software testing"` parent skills.
- **Pinned Gemini Model & Removed Silent Model Fallbacks:**
  - Pinned `GeminiJudgeProvider` strictly to `config.GEMINI_JUDGE_MODEL` (`gemini-3.8-flash`).
  - Removed multi-model fallback list (`GEMINI_2_5_FLASH_CANDIDATES`), ensuring score reproducibility across evaluations.
  - 503 errors trigger exponential backoff retries (`1s, 2s, 4s`) on the **same** model; 404 errors immediately fail over to the outer provider chain (Gemini -> Groq -> OpenRouter).

---

## [Version 2026.09.1] — 2026-09-14

### Added
- **Deterministic Taxonomy Hierarchy:**
  - Extended `taxonomy.yaml` with parent-child relationships via `includes:` (41 parent skills encompassing specific subskills).
  - Implemented `_hierarchy_lookup()`, `_reverse_hierarchy_lookup()`, `get_encompassed_subskills()`, `get_parent_skills()`, `is_parent_of()`, and `get_encompassed_skills_for_ids()`.
- **4-Tier Source Multiplier Framework:**
  - Updated `_calculate_source_multiplier()` to award `0.80` for subskills logically encompassed by candidate's explicit parent skills (replacing the previous flat `0.50` penalty).
- **Balanced 4-Tier Judge Evaluation Rubric:**
  - Updated `JUDGE_SYSTEM_PROMPT` and `build_judge_prompt()` to include `50–75%` credit for broader domain logical coverage, alongside `90–100%` full credit, `1–49%` weak partial credit, and `0%` no credit.
- **Work Experience Calculation:**
  - Added `calculate_total_experience_years()` supporting flexible date parsing (`%m/%Y`, `%Y-%m`, etc.), invalid range handling, and concurrent role aggregation.
- **70 / 20 / 10 Weighted Scoring Formula:**
  - Implemented balanced formula allocating 70% to required skills, 20% to nice-to-have skills, and 10% to work experience ratio.

---

## [Version 2026.09.0] — 2026-09-13

### Added
- **Curated Taxonomy Expansion:**
  - Expanded `taxonomy.yaml` from 79 to 317 canonical skills across 9 core engineering domains (Backend, Frontend, Mobile, DevOps/Cloud, QA/Testing, Machine Learning, Data Engineering, Database, Cybersecurity).
  - 0 duplicate IDs, 0 alias collisions, strict lowercase formatting.
- **Distributed Caching Backend:**
  - Implemented dual Redis / In-Memory caching backend with SHA-256 key hashing and 1-hour TTL.
- **Multi-Provider Semantic LLM Judge Chain:**
  - Implemented provider-neutral `query_judge` supporting Google Gemini, Groq, and OpenRouter with failover.
- **Security & PII Redaction Chain:**
  - Integrated `redact()` and `assert_clean()` ensuring no PII is transmitted to external inference providers.
  - Added magic byte file validation for PDF (`%PDF`) and DOCX (`PK\x03\x04`).

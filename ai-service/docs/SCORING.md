# Scoring Methodology & Taxonomy Hierarchy Deep-Dive

This document provides a comprehensive technical breakdown of the candidate capability ranking algorithm, the 70/20/10 weighted scoring system, deterministic taxonomy hierarchy mappings, and LLM judge evaluation tiers.

---

## 1. The Core 70 / 20 / 10 Scoring Formula

The candidate's final score ($S \in [0, 100]$) is computed by combining three independent assessment dimensions:

$$S = \left( C_{\text{required}} + C_{\text{preferred}} + C_{\text{experience}} \right) \times 100$$

Where:
- **$C_{\text{required}}$ (Required Skills Component — 70%):**
  $$C_{\text{required}} = \overline{\text{SkillScore}}_{\text{required}} \times 0.70$$
- **$C_{\text{preferred}}$ (Nice-to-Have Skills Component — 20%):**
  $$C_{\text{preferred}} = \overline{\text{SkillScore}}_{\text{preferred}} \times 0.20$$
- **$C_{\text{experience}}$ (Work Experience Component — 10%):**
  $$C_{\text{experience}} = R_{\text{experience}} \times 0.10$$

---

## 2. Individual Skill Scoring & Source Multipliers

For each requirement $r$, the final skill score is the product of semantic satisfaction and credential verification confidence:

$$\text{FinalSkillScore}(r) = \text{SatisfactionPercent}(r) \times \text{SourceMultiplier}(r)$$

### Source Multiplier Tiers

The source multiplier assigns evidence confidence based on structured candidate credentials vs narrative mentions:

| Tier | Source Multiplier | Criteria | Technical Rationale |
|:---:|:---:|---|---|
| **Tier 1: Direct Explicit Match** | **`1.00`** | Requirement matches a canonical ID directly listed in `candidate.skills`, `candidate.inferred_skills`, or `candidate.certifications`. | Maximum confidence; verified in candidate structured summary. |
| **Tier 2: Hierarchical Parent Match** | **`0.80`** | Requirement is logically encompassed by an explicit parent skill in candidate's profile (e.g. candidate has `Machine Learning`, requirement is `Linear Regression`). | High confidence; candidate possesses verified parent competency that covers foundational subskills. |
| **Tier 3: Narrative Experience Match** | **`0.50`** | Requirement is found only in unstructured project descriptions, technologies, or job role descriptions. | Medium confidence; unverified passing mention in narrative text. |
| **Tier 4: Fallback / Unresolvable** | **`0.50`** | Requirement cannot be resolved in taxonomy or candidate has no matching signal. | Conservative default. |

#### Tie-Breaking Rule:
If a requirement matches both a parent skill and narrative text, **Hierarchical Parent Match (`0.80`) takes precedence** because structured credentials represent a stronger signal of technical ability than passing narrative mentions.

---

## 3. Deterministic Taxonomy Hierarchy System

The taxonomy (`app/skills/taxonomy.yaml`) defines canonical technical skills organized across 9 engineering domains. Hierarchy is modeled deterministically using the `includes:` key.

### Hierarchy Model
- **Direct & Transitive Closures:**  
  `canonicalize.py` builds an in-memory graph of all `includes:` relationships and computes transitive subskills via breadth-first traversal (`_hierarchy_lookup()`).
- **Reverse Lookup:**  
  Maps any child skill back to all ancestor parent skills (`_reverse_hierarchy_lookup()`).

### Parent Substring Collision Prevention
To prevent incidental substring collisions (e.g., requirement `"Software Testing Life Cycle (STLC)"` matching parent `skill.software_testing` purely by substring):
- `_extract_requirement_skill_ids()` filters out any extracted taxonomy ID that is a hierarchy parent (`is_hierarchy_parent(id) == True`) **unless** the entire requirement string directly canonicalizes to that parent ID.
- Standalone requirements (e.g. `"Software Testing"` or `"Machine Learning"`) continue to resolve directly to their parent skill IDs.

---

## 4. LLM Semantic Capability Judge Framework

Batched requirements are evaluated by the semantic judge prompt (`app/prompts/registry.py`) using a 4-tier rubric:

| Tier | Credit Range | Prompt Guideline |
|---|:---:|---|
| **Full Credit** | **`90% – 100%`** | Candidate evidence explicitly demonstrates direct experience with the requirement, including its material actions and operations. |
| **Broader Domain Coverage** | **`50% – 75%`** | Candidate evidence explicitly demonstrates a broader, higher-level technical capability or parent domain that logically encompasses the required sub-skill (e.g., proven ML experience covering linear regression). |
| **Vague / Weak Partial Credit** | **`1% – 49%`** | Evidence is vague, incidental, or names a weakly related tool without proving logical coverage or actual operational usage. |
| **No Credit** | **`0%`** | Evidence is completely absent or irrelevant. |

---

## 5. Work Experience Calculation

Experience duration is calculated from all role entries in `candidate.experience` (`app/pipeline/ranking.py`):
- Start dates parsed across standard formats (`%m/%Y`, `%Y-%m`, `%Y`, etc.).
- Missing end dates fall back to current date (`date.today()`).
- Inverted date ranges ($end < start$) contribute `0.0`.
- Overlapping roles are summed to credit concurrent freelance/part-time positions.

### Experience Ratio Calculation:
- If `min_experience_years` is unset (`None`) or `0`:
  $$R_{\text{experience}} = 1.0 \quad (\text{full 10\% awarded})$$
- If `min_experience_years > 0`:
  $$R_{\text{experience}} = \min\left( \frac{\text{candidate\_total\_years}}{\text{min\_experience\_years}}, 1.0 \right)$$

---

## 6. Output Breakdown Contract Specification

The `RankingResult.breakdown` dictionary returned by the ranking pipeline includes the following fields:

```json
{
  "scoring_version": "weighted-70-20-10-v1",
  "required_component": 0.56,
  "nice_to_have_component": 0.01,
  "experience_component": 0.058,
  "candidate_total_years": 1.74,
  "experience_ratio": 0.58,
  "required_skills_total": 8,
  "required_satisfaction_average": 0.95,
  "nice_to_have_skills_total": 4,
  "nice_to_have_satisfaction_average": 0.0625,
  "hard_skill_score": 0.9506,
  "hard_skill_weight": 1.0,
  "semantic_weight": 0.0,
  "taxonomy_version": "2026.09",
  "judge_prompt_version": "ranking-judge-v1"
}
```

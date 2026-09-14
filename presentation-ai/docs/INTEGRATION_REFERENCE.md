# Master Integration Reference: Presentation Analysis & Video Demo Analysis

> **Status:** Authoritative Integration Reference  
> **Version:** 1.1.0  
> **Component:** Presentation Analysis Subsystem (`presentation-ai`) [IMPLEMENTED]  
> **Integration Target:** Video Demo Analysis Subsystem (`video-ai`) [PLANNED]  
> **Cross-Modal Layer:** Multi-Modal Evaluator [PROPOSED / SPECIFIED]  
> **Date:** September 2026  

---

## 1. System Overview

The **Applicant Evaluation Platform** evaluates technical job applicants across two independent artifacts:
1. **Applicant Presentation (`.pptx`)**: The slide deck summarizing the applicant's engineering project, methodology, architecture, and benchmark results.
2. **Applicant Video Demo (`.mp4` / `.webm`)**: The recorded demonstration and oral walkthrough presented by the applicant.

Both analysis subsystems operate independently at the ingestion and single-modal analysis layer, and converge at a **deterministic Cross-Modal Integration Layer** that evaluates cross-modal alignment, detects contradictions, identifies omissions, and computes a unified final evaluation report for Human Resources (HR) decision support.

```mermaid
graph TD
    subgraph Presentation Subsystem [IMPLEMENTED]
        A[Applicant .pptx] --> B[Deterministic PPTX Extraction]
        B --> C[Normalization & Cleaning]
        C --> D[Claim Extraction & Classification]
        D --> E1[Track A: Web-Grounded Fact-Check]
        D --> E2[Track B: Plausibility Check]
        E1 --> F[Presentation Analysis Result]
        E2 --> F
        F --> G[Deterministic Presentation Scores]
    end

    subgraph Video Demo Subsystem [PLANNED]
        V[Applicant Demo Video] --> W[ASR / Audio Extraction]
        W --> X[Speaker Diarization]
        X --> Y[Spoken Claim Extraction]
        Y --> Z[Video Demo Analysis Result]
    end

    subgraph Cross-Modal Integration Layer [PROPOSED SPECIFICATION]
        F --> CM[Deterministic & Semantic Claim Matcher]
        Z --> CM
        CM --> CD[Contradiction Detection]
        CM --> OD[Omission Detection]
        CM --> CS[Cross-Modal Consistency Scoring]
        G --> FS[Final Composite Applicant Score]
        CS --> FS
        FS --> R[Unified Evaluation Report for HR]
    end
```

---

## 2. Component Responsibilities & Implementation State

| Subsystem | State | Input | Core Responsibilities | Output Contract |
|---|---|---|---|---|
| **Presentation Analysis** (`presentation-ai`) | **IMPLEMENTED** | `.pptx` file bytes | • Extract slide text, titles, tables, charts, notes<br>• Normalize bilingual Arabic/English content<br>• Extract and classify claims into 7 canonical types<br>• Track A: Ground objective facts via web search<br>• Track B: Evaluate project metrics plausibility<br>• Generate interview questions and corrections<br>• Calculate deterministic presentation sub-scores | `PresentationAnalysisResult`<br>([`app/schemas/presentation.py`](file:///d:/Projects/AMIT%20INTERN/presentation-ai/presentation-ai/app/schemas/presentation.py)) |
| **Video Demo Analysis** (`video-ai`) | **PLANNED** | Video / Audio stream | • Transcribe speech to text with word-level timestamps<br>• Identify and isolate applicant vs interviewer speakers<br>• Extract spoken claims, metrics, and architecture claims<br>• Tag spoken claims with canonical subject/property taxonomy<br>• Calculate independent video clarity and quality scores | `VideoDemoAnalysisResult`<br>([`app/schemas/integration.py`](file:///d:/Projects/AMIT%20INTERN/presentation-ai/presentation-ai/app/schemas/integration.py)) |
| **Cross-Modal Integration Layer** | **PROPOSED** | `PresentationAnalysisResult` + `VideoDemoAnalysisResult` | • Align presentation claims with spoken claims<br>• Identify cross-modal agreements and elaborations<br>• Detect quantitative and qualitative contradictions<br>• Identify high-importance presentation omissions<br>• Identify unsupported spoken overclaims<br>• Compute deterministic Consistency Score & Final Applicant Score | `CrossModalAnalysisResult`<br>([`app/schemas/integration.py`](file:///d:/Projects/AMIT%20INTERN/presentation-ai/presentation-ai/app/schemas/integration.py)) |

---

## 3. End-to-End Flow

1. **Ingestion & Preprocessing**:
   - The user or workflow orchestrator submits the `.pptx` file to `POST /api/v1/presentation/analyze` and the demo video to the Video AI service.
2. **Presentation Pipeline Execution [IMPLEMENTED]**:
   - `extract_pptx` extracts text, tables, charts, notes with per-slide traceability.
   - `normalize` handles whitespace, de-duplication, and Arabic Unicode normalization.
   - `claim_extraction` extracts claims with canonical taxonomy tags (`subject`, `property`, `value`, `unit`, `claim_type`, `track`, `importance`).
   - `fact_check` dispatches claims:
     - **Track A (Objective)**: Grounded web search with source verification.
     - **Track B (Project-Specific)**: Deterministic hard-rules filter followed by batched LLM contextual plausibility.
   - `scoring` computes deterministic importance-weighted scores (0–100).
   - `postprocess` builds structured issues, interview questions, and evidence-grounded corrections.
3. **Video Demo Pipeline Execution [PLANNED]**:
   - Speech-to-text transcription generates timestamped segments.
   - Diarization assigns segments to `SPEAKER_00` (Applicant).
   - Spoken claim extraction extracts `SpokenClaim` items with timestamps (`timestamp_start_s`, `timestamp_end_s`) and canonical taxonomy tags.
4. **Cross-Modal Alignment & Scoring [PROPOSED]**:
   - Deterministic taxonomy matching is attempted first: matching `(subject, property)` pairs.
   - Semantic embedding matching (multilingual E5 / Gemini embeddings) aligns descriptive statements.
   - Discrepancy analyzer checks for value mismatches (e.g. Slide says `85%`, speaker says `95%`).
   - Omission analyzer checks if any `high` importance presentation claim was unmentioned in the video.
   - Scoring engine computes the `ConsistencyScore` and `FinalApplicantScore`.

---

## 4. Presentation Analysis Input & Output Contracts [IMPLEMENTED]

### 4.1 Input Contract (`POST /api/v1/presentation/analyze`)
- **HTTP Method**: `POST`
- **Content-Type**: `multipart/form-data`
- **Fields**:
  - `file` (*required*, binary): The `.pptx` file.
    - Allowed extension: `.pptx` (case-insensitive).
    - Validation: Must start with ZIP header magic bytes (`PK\x03\x04`).
    - Maximum size: `25 MB` (enforced at web layer via `MAX_CONTENT_LENGTH`).
  - `applicant_id` (*optional*, string): Applicant identifier for tracking.
  - `job_id` (*optional*, string): Job opening identifier.

### 4.2 Output Contract (`PresentationAnalysisResult`)
The schema is defined in [`app/schemas/presentation.py`](file:///d:/Projects/AMIT%20INTERN/presentation-ai/presentation-ai/app/schemas/presentation.py):

```json
{
  "analysis_id": "ANL-a1b2c3d4e5f6",
  "status": "completed",
  "completeness": {
    "slides_total": 5,
    "slides_processed": 5,
    "slides_failed": 0
  },
  "presentation": {
    "filename": "applicant_deck.pptx",
    "slide_count": 5
  },
  "scores": {
    "overall": 88,
    "fact_accuracy": 92,
    "evidence_coverage": 85,
    "claim_reliability": 92
  },
  "summary": {
    "total_claims": 6,
    "supported": 2,
    "contradicted": 0,
    "project_unsupported": 3,
    "plausibility_flag": 1,
    "unclear": 0,
    "not_checkable": 0
  },
  "claims": [
    {
      "claim_id": "CLM-001",
      "slide_number": 2,
      "text": "Our model achieved 94.2% accuracy on the test split.",
      "claim_type": "performance",
      "track": "project_specific",
      "importance": "high",
      "subject": "model",
      "property": "accuracy",
      "value": 94.2,
      "unit": "%"
    }
  ],
  "verifications": [
    {
      "claim_id": "CLM-001",
      "status": "project_unsupported",
      "confidence": 0.85,
      "reason": "Reported 94.2% accuracy is within the plausible range for standard image classification benchmarks.",
      "evidence": []
    }
  ],
  "issues": [],
  "suggested_interview_questions": []
}
```

---

## 5. Video Demo Analysis Contract & Spoken Claim Extraction [PLANNED]

### 5.1 Demo AI Output Contract (Verified Runtime Output)
Demo AI transcribes speech into text with timestamped segments:

```json
{
  "success": true,
  "language": "ar",
  "language_probability": 0.9854,
  "text": "full concatenated transcript...",
  "segments": [
    {"start": 0.0, "end": 3.42, "text": "..."}
  ]
}
```

### 5.2 Spoken Claim Schema (`SpokenClaim`)
A separate spoken claim extraction stage (built within the Demo AI codebase) transforms raw transcript segments into structured spoken claims conforming to [`app/schemas/integration.py`](file:///d:/Projects/AMIT%20INTERN/presentation-ai/presentation-ai/app/schemas/integration.py):

```json
{
  "spoken_claim_id": "SPK-001",
  "text": "On the test dataset, we achieved ninety-four point two percent accuracy.",
  "start": 45.2,
  "end": 52.0,
  "source_segment_indices": [12, 13],
  "claim_type": "performance",
  "subject": "model",
  "property": "accuracy",
  "value": 94.2,
  "unit": "%",
  "language": "en"
}
```

---


## 6. Shared Data Structures & Claim Representation [IMPLEMENTED]

### 6.1 Claim Canonical Representation
To enable deterministic comparison across modalities, claims on both sides share the canonical taxonomy attributes ([`app/taxonomy/`](file:///d:/Projects/AMIT%20INTERN/presentation-ai/presentation-ai/app/taxonomy/)):

1. **`claim_type`**: One of the 7 mutually exclusive categories:
   - `performance`: Quantitative results (accuracy, latency, throughput, error rate, BLEU).
   - `dataset`: Dataset characteristics (sample count, split ratio, class distribution).
   - `architecture`: Structural design (layers, parameter counts, pipeline components).
   - `technology`: Specific frameworks, libraries, hardware, or database engines used.
   - `algorithm`: Specific mathematical or algorithmic techniques (AdamW, LoRA, Dijkstra).
   - `capability`: Qualitative abilities without specific numeric metrics (e.g. "supports real-time inference").
   - `business`: Financial, market, or operational impact metrics (e.g. "saved $50k/month").
2. **`track`**:
   - `objective`: General technical facts verifiable against external public knowledge.
   - `project_specific`: Internal project accomplishments and empirical results.
3. **`importance`**: `high`, `medium`, or `low`.
4. **Canonical Quadruple**:
   - `subject`: Normalized entity (e.g., `BERT`, `ResNet-50`, `PostgreSQL`).
   - `property`: Canonical property name from `app/taxonomy/properties.py` (e.g., `accuracy`, `latency`, `dataset_size`).
   - `value`: Numeric scalar or normalized string.
   - `unit`: Normalized unit (e.g., `%`, `ms`, `img/s`, `samples`).

> **Note on Qualitative Claims:** Qualitative claims (e.g. *"We used PostgreSQL as our primary database"* or *"The backend was built in Flask"*) are valid claims under `technology`/`architecture`/`capability`. They naturally have `property=None, value=None, unit=None` and are NOT invalid. They are matched across modalities via Layer 2 semantic similarity.

### 6.2 Stable Identifiers & Traceability
- **Presentation Claims**: `CLM-001`, `CLM-002`, ... (always paired with `slide_number`).
- **Video Claims**: `VCLM-001`, `VCLM-002`, ... (always paired with `timestamp_start_s` and `timestamp_end_s`).
- **Alignments**: `ALN-001`, `ALN-002`, ... (referencing `presentation_claim_id` and `video_claim_id`).

---

## 7. Cross-Modal Matching & Comparison Logic [PROPOSED]

### 7.1 Multi-Layer Alignment Algorithm

```
                  ┌─────────────────────────────────────┐
                  │ Presentation Claim + Video Claim    │
                  └──────────────────┬──────────────────┘
                                     │
                 [Layer 1: Deterministic Taxonomy Match]
                 Is subject AND property identical?
                                ├──► YES: Direct Comparison
                                │    (Compare Value/Unit)
                                │
                                └──► NO
                                     │
                 [Layer 2: Semantic Embedding Match]
                 Cosine similarity(E_pres, E_video) >= 0.78?
                 (0.78 is a proposed heuristic threshold)
                                ├──► YES: Semantic Alignment
                                │
                                └──► NO: Unmatched / Independent
```

*Status of Similarity Threshold (0.78):*  
The threshold of `0.78` is a **proposed heuristic default** based on multilingual cosine similarity ranges for E5/Gemini embeddings. It is **configurable** in settings and will be calibrated against labeled cross-modal pairs during the Video Demo integration phase.

### 7.2 Detection of Cross-Modal Discrepancies

#### A. Agreement (`agreement`)
- **Condition**: Presentation claim and Video claim match on subject/property and have identical or mathematically equivalent values (within $\pm 1\%$ tolerance for floating point numbers), or share semantic similarity $\ge 0.78$ without conflicting facts.
- **Example**: Slide states *"Accuracy: 94.2%"*, Speaker says *"We reached 94.2% accuracy"*.

#### B. Contradiction (`contradiction`)
- **Condition**: Both claims match on subject and property (or have high semantic overlap), but state conflicting values or mutually exclusive claims.
- **Example**: Slide states *"Latency: 120ms"*, Speaker says *"Our latency was 12 milliseconds"*.
- **Impact**: Generates a high-severity contradiction issue and triggers an interview probe question.

#### C. Omission in Video (`omitted_in_video`)
- **Condition**: Presentation contains a `high` importance claim (e.g. critical benchmark result), but no matching spoken claim is found in the video transcript (semantic similarity $< 0.78$ across all spoken claims).
- **Impact**: Penalizes `ConsistencyScore` moderately; flagged for interviewer review.

#### D. Unsupported Spoken Overclaim (`unsupported_spoken`)
- **Condition**: Speaker asserts a high-magnitude claim during the demo (e.g., *"We beat SOTA by 15%"*), but no supporting slide or mention exists in the presentation deck.
- **Impact**: Flagged as an unsupported claim requiring interview verification.

---

## 8. Scoring Architecture & Separation of Concepts [IMPLEMENTED & PROPOSED]

The platform enforces a **strict, non-ambiguous separation** between single-modal quality and cross-modal consistency:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          APPLICANT EVALUATION SCORES                        │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ 1. Presentation Overall Score (0-100)│ • Evaluates slide deck content alone  │
│    [IMPLEMENTED in Presentation AI]  │ • Fact Accuracy, Evidence, Reliability│
├──────────────────────────────────────┼──────────────────────────────────────┤
│ 2. Video Overall Score (0-100)       │ • Evaluates video demo delivery alone │
│    [PLANNED in Video Demo AI]        │ • Delivery clarity, spoken accuracy   │
├──────────────────────────────────────┼──────────────────────────────────────┤
│ 3. Consistency Score (0-100)         │ • Cross-modal alignment quality      │
│    [PROPOSED in Integration Layer]   │ • Contradiction & omission penalties  │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ 4. FINAL APPLICANT SCORE (0-100):                                            │
│    FinalScore = round(0.40 * PresentationScore + 0.30 * VideoScore + 0.30 * ConsistencyScore)│
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.1 Scoring Formulas

#### 1. Presentation Overall Score (`Scores.overall`) [IMPLEMENTED]
$$\text{FactAccuracy} = \text{round}\left(100 \cdot \frac{\sum w_i \cdot s_i}{\sum w_i}\right)$$
$$\text{EvidenceCoverage} = \text{round}\left(100 \cdot \frac{\sum w_i \cdot b_i}{\sum w_i}\right)$$
$$\text{PresentationScore} = \text{round}(0.50 \cdot \text{FactAccuracy} + 0.25 \cdot \text{EvidenceCoverage} + 0.25 \cdot \text{ClaimReliability})$$
- **Implementation**: Pure deterministic function in [`app/pipeline/scoring.py`](file:///d:/Projects/AMIT%20INTERN/presentation-ai/presentation-ai/app/pipeline/scoring.py).
- **Weights**: `high` = 3, `medium` = 2, `low` = 1.

#### 2. Cross-Modal Consistency Score (`CrossModalScores.consistency_score`) [PROPOSED]
$$\text{Base} = 100$$
$$\text{Penalty}_{\text{contradiction}} = \sum_{c \in \text{Contradictions}} w(c.\text{importance}) \cdot 15$$
$$\text{Penalty}_{\text{omission}} = \sum_{o \in \text{HighOmissions}} 8$$
$$\text{ConsistencyScore} = \max(0, \min(100, \text{Base} - \text{Penalty}_{\text{contradiction}} - \text{Penalty}_{\text{omission}}))$$

#### 3. Final Applicant Score (`CrossModalScores.final_applicant_score`) [PROPOSED]
$$\text{FinalScore} = \text{round}(0.40 \cdot \text{PresentationScore} + 0.30 \cdot \text{VideoScore} + 0.30 \cdot \text{ConsistencyScore})$$
- If no video is submitted, `FinalScore = PresentationScore` (with `status="partial"`).

---

## 9. Token Usage & Cost Model [IMPLEMENTED]

### 9.1 Measured Baseline Token Statistics (12 Evaluation Presentations)

Based on live benchmark evaluation runs on the labeled dataset (`eval/datasets/presentation-extraction/v1/`):

| Metric | Measured Baseline (Unbatched) | Measured Baseline (Batched Track B) |
|---|---|---|
| **Average Slides per Presentation** | 2.33 slides | 2.33 slides |
| **Average Claims per Presentation** | 3.17 claims | 3.17 claims |
| **Average Input Tokens / Presentation** | ~2,613 tokens | ~1,850 tokens |
| **Average Output Tokens / Presentation** | ~282 tokens | ~220 tokens |
| **Average Total Tokens / Presentation** | **~2,895 tokens** | **~2,070 tokens** |
| **Average LLM Calls / Presentation** | 4.67 calls | 3.00 calls |
| **Minimum Measured Tokens (1 slide)** | ~750 tokens | ~750 tokens |
| **Maximum Measured Tokens (4 slides)** | ~4,200 tokens | ~3,100 tokens |

### 9.2 Formulaic Cost Calculation
$$\text{Cost}_{\text{presentation}} = (\text{Tokens}_{\text{in}} \cdot P_{\text{in}}) + (\text{Tokens}_{\text{out}} \cdot P_{\text{out}})$$

*Example Pricing Assumption (Gemini 2.5/3.5 Flash Tier @ \$0.075 / 1M input tokens, \$0.30 / 1M output tokens):*
$$\text{Cost} = (0.001850 \cdot \$0.075) + (0.000220 \cdot \$0.30) \approx \$0.000138 + \$0.000066 = \mathbf{\$0.000204 \text{ per presentation}}$$

---

## 10. Security & Untrusted Input Boundaries [IMPLEMENTED]

1. **Untrusted Presentation Content**:
   - Slide text, tables, and speaker notes are untrusted user input.
   - All extraction prompts enforce strict bounding delimiters:
     `<<<PRESENTATION_CONTENT_START>>>` ... `<<<PRESENTATION_CONTENT_END>>>`.
   - The model is explicitly instructed that text inside boundaries cannot alter system instructions.
2. **File Handling & Path Traversal**:
   - Filenames are sanitized via `secure_filename()`.
   - File uploads are validated for ZIP magic bytes (`PK\x03\x04`) and capped at 25MB before memory buffer allocation.
3. **Sensitive Data & API Keys**:
   - API keys are loaded via `config.settings.Settings` from environment variables, never logged or serialized into response bodies.

---

## 11. Complete Integration Response Example (`CrossModalAnalysisResult`)

```json
{
  "schema_version": "1.0.0",
  "status": "completed",
  "presentation_analysis_id": "ANL-89fbc0123456",
  "video_reference": "applicant_demo.mp4",
  "alignments": [
    {
      "presentation_claim_id": "CLM-001",
      "spoken_claim_id": "SPK-001",
      "relationship": "consistent",
      "confidence": 0.95,
      "reason": "Both presentation slide 2 and spoken demo at 00:45 claim 94.2% test accuracy on the CNN model.",
      "evidence_quote": "we achieved ninety-four point two percent accuracy",
      "timestamp_start": 45.2,
      "timestamp_end": 52.0
    }
  ],
  "summary": {
    "total_alignments": 1,
    "consistent": 1,
    "contradicted": 0,
    "additional": 0,
    "missing": 0,
    "unrelated": 0
  },
  "overall_consistency_score": 95
}
```

---

## 12. Integration Implementation Checklist

| Item | Status | Notes |
|---|---|---|
| Presentation Ingestion API (`POST /api/v1/presentation/analyze`) | **COMPLETED** | Fully implemented and hardened with 25MB limit and ZIP validation. |
| Presentation Output Schema (`PresentationAnalysisResult`) | **COMPLETED** | Stable Pydantic model with strict validation. |
| Canonical Claim ID Generation (`CLM-xxx`) | **COMPLETED** | Traceable per-slide claim identifiers. |
| 7-Category Claim Type Classification Taxonomy | **COMPLETED** | 97.4% accuracy baseline on labeled benchmark. |
| Track A (Objective) Grounded Fact-Checking | **COMPLETED** | Web-search grounding with strict source URL validation. |
| Track B (Project-Specific) Plausibility & Batching | **COMPLETED** | Batched evaluation with deterministic individual fallback. |
| Deterministic Presentation Scoring | **COMPLETED** | 100% deterministic pure function. |
| Machine-Readable Integration Schemas (`integration.py`) | **COMPLETED** | Finalized Pydantic schemas for `SpokenClaim`, `ClaimAlignment`, `CrossModalSummary`, `CrossModalAnalysisResult`. |
| Cross-Modal Claim Matcher | **PLANNED** | Integration layer matching algorithm defined in §7. |
| Cross-Modal Consistency Engine | **PLANNED** | Formula and penalty architecture defined in §8. |
| Video Demo Analysis Service | **PLANNED** | External subsystem producing transcript segments and `SpokenClaim` items. |


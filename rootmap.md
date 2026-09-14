# Applicant Presentation AI

## 1. Project Overview

Applicant Presentation AI is an AI-powered system that analyzes a presentation submitted by a job applicant before an interview or technical demo.

The system receives a PowerPoint presentation and produces a structured analysis of the content.

The main goals are to:

1. Extract the content of the presentation.
2. Identify factual and technical claims.
3. Verify the claims using available evidence.
4. Detect incorrect, unsupported, or misleading claims.
5. Report the exact slide where each claim appears.
6. Suggest a correction for incorrect claims.
7. Calculate a presentation accuracy score.
8. Produce structured output that can later be used by the Demo Analysis system.
9. Store normalized claims that can be compared with what the applicant says during the demo.

The project is designed as an independent component.

Later, its output can be combined with the Applicant Demo AI system to calculate a final applicant consistency score.

---

# 2. Project Scope

The Presentation AI system focuses only on the applicant's presentation.

It does not analyze the applicant's voice or video.

The system starts with:

```text
Applicant Presentation
        │
        ▼
PowerPoint File
        │
        ▼
Content Extraction
        │
        ▼
Claim Extraction
        │
        ▼
Claim Verification
        │
        ▼
Claim Classification
        │
        ▼
Scoring
        │
        ▼
Structured Report
```

The video analysis belongs to a separate project.

---

# 3. Input

## 3.1 Primary Input

The primary input is a PowerPoint presentation.

Supported format:

```text
.pptx
```

Example:

```text
applicant_presentation.pptx
```

The presentation may contain:

* Text
* Titles
* Bullet points
* Tables
* Images
* Charts
* Diagrams
* Speaker notes
* Hyperlinks
* Technical specifications
* Metrics
* Architecture descriptions
* Model performance results
* Dataset information
* Technology claims

---

# 4. Input API

The recommended API accepts a multipart file upload.

Example:

```http
POST /api/v1/presentation/analyze
Content-Type: multipart/form-data
```

Request:

```text
file = applicant_presentation.pptx
```

Optional metadata can be included:

```json
{
  "applicant_id": "APP-001",
  "job_id": "JOB-123"
}
```

The system should not depend on the applicant ID or job ID for the core analysis.

They are metadata used for tracking and integration.

---

# 5. Processing Pipeline

The complete pipeline is:

```text
                    PPTX
                     │
                     ▼
             File Validation
                     │
                     ▼
             Content Extraction
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
      Text         Tables       Images
        │            │            │
        └────────────┼────────────┘
                     ▼
              Content Cleaning
                     │
                     ▼
              Claim Extraction
                     │
                     ▼
             Claim Normalization
                     │
                     ▼
              Evidence Retrieval
                     │
                     ▼
               Fact Checking
                     │
                     ▼
             Claim Classification
                     │
                     ▼
                  Scoring
                     │
                     ▼
              Report Generation
                     │
                     ▼
                  JSON
```

---

# 6. Step 1 — File Validation

Before processing the presentation, validate the uploaded file.

The system should check:

* File extension
* MIME type
* File size
* File integrity
* Whether the file can be opened as a valid PowerPoint file

Example validation:

```text
File:
applicant_presentation.pptx

Format:
PPTX

Status:
Valid
```

Invalid files should return a structured error.

Example:

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_FILE",
    "message": "The uploaded file is not a valid PowerPoint presentation."
  }
}
```

---

# 7. Step 2 — Presentation Content Extraction

The system extracts content slide by slide.

Every extracted element must keep its slide number.

This is important because the final report needs to tell the HR or reviewer exactly where a claim appears.

Example:

```json
{
  "slide_number": 4,
  "title": "Model Performance",
  "elements": [
    {
      "type": "text",
      "content": "Our model achieved 95% accuracy."
    },
    {
      "type": "text",
      "content": "The model was trained on 50,000 images."
    }
  ]
}
```

---

# 8. Extracted Content

The extraction layer should support:

## Text

```text
Titles
Paragraphs
Bullet points
Labels
Captions
```

## Tables

Tables should be converted into structured rows and columns.

Example:

```json
{
  "type": "table",
  "headers": [
    "Model",
    "Accuracy"
  ],
  "rows": [
    [
      "Random Forest",
      "95%"
    ],
    [
      "SVM",
      "91%"
    ]
  ]
}
```

## Images

Images should be extracted from the presentation.

The system can optionally send images to a vision model for analysis.

This is useful for:

* Architecture diagrams
* Charts
* Screenshots
* Tables embedded as images
* Technical diagrams

Image analysis should remain optional in the first version.

---

# 9. Step 3 — Content Normalization

Raw PowerPoint content should be converted into a normalized internal representation.

Example:

```json
{
  "slide_number": 5,
  "content": [
    {
      "type": "heading",
      "text": "Model Performance"
    },
    {
      "type": "paragraph",
      "text": "The model achieved 95% accuracy."
    },
    {
      "type": "paragraph",
      "text": "Training was performed using 50,000 images."
    }
  ]
}
```

Normalization should remove:

* Duplicate text
* Empty elements
* Formatting artifacts
* Broken whitespace
* Unnecessary PowerPoint metadata

It should not remove information that can affect the meaning of a claim.

---

# 10. Step 4 — Claim Extraction

Not every sentence in a presentation is a factual claim.

For example:

```text
Welcome to our project.
```

is not a useful fact-checking claim.

But:

```text
Our model achieved 95% accuracy.
```

is a factual claim.

The claim extraction layer identifies statements that can be verified.

---

# 11. Claim Types

Claims can be classified into several categories.

## Performance Claims

Examples:

```text
The model achieved 95% accuracy.

The system reduced latency by 40%.

The model has an R² score of 0.96.
```

## Dataset Claims

Examples:

```text
The model was trained on 100,000 images.

The dataset contains 20 classes.
```

## Architecture Claims

Examples:

```text
The system uses a microservices architecture.

The backend uses FastAPI.
```

## Technology Claims

Examples:

```text
The system uses PostgreSQL.

We use YOLOv8 for object detection.
```

## Algorithm Claims

Examples:

```text
We use Random Forest for classification.

The model uses gradient boosting.
```

## Capability Claims

Examples:

```text
The system works in real time.

The application supports offline inference.
```

## Business or General Claims

Examples:

```text
The system reduces maintenance costs.

The solution can reduce processing time.
```

---

# 12. Claim Object

Every extracted claim should have a unique ID.

Example:

```json
{
  "claim_id": "CLM-0001",
  "slide_number": 7,
  "text": "Our model achieved 95% accuracy.",
  "claim_type": "performance",
  "importance": "high"
}
```

Recommended fields:

```text
claim_id
slide_number
text
claim_type
importance
source_element
```

---

# 13. Claim Importance

Not every claim should have the same impact on the final score.

Use three levels:

```text
high
medium
low
```

Example:

### High

```text
Our model achieved 98% accuracy.
```

### Medium

```text
The system supports three database engines.
```

### Low

```text
The interface is easy to use.
```

Performance and technical claims should usually receive higher importance.

---

# 14. Step 5 — Evidence Retrieval

Fact checking requires evidence.

The system should retrieve evidence relevant to each claim.

Possible evidence sources include:

* Applicant-provided project files
* Project documentation
* Dataset documentation
* Model evaluation results
* Trusted external sources
* Official technology documentation
* Research papers
* Public datasets

The evidence source must be recorded.

Example:

```json
{
  "source_type": "project_documentation",
  "source": "model_evaluation.json",
  "evidence": "Validation accuracy: 92.4%"
}
```

---

# 15. Evidence Hierarchy

Evidence should have different levels of trust.

Recommended priority:

```text
1. Applicant project artifacts
2. Applicant-generated evaluation results
3. Official documentation
4. Research papers
5. Trusted public sources
6. General web sources
```

The system should prefer project-specific evidence when the claim describes the applicant's own project.

For example:

```text
Our model achieved 95% accuracy.
```

A Google search cannot prove whether the applicant's model achieved 95%.

The system needs project evidence.

---

# 16. Important Fact-Checking Rule

The system must distinguish between:

```text
False
```

and:

```text
Unsupported
```

These are not the same.

Example:

The applicant says:

```text
Our model achieved 95% accuracy.
```

If project evidence says:

```text
Accuracy = 81%
```

Then:

```text
status = contradicted
```

But if there is no evidence showing the actual accuracy:

```text
status = unsupported
```

The system should not automatically call an unsupported claim false.

---

# 17. Claim Status

Recommended statuses:

```text
supported
partially_supported
contradicted
unsupported
unclear
not_checkable
```

Meaning:

### supported

Evidence supports the claim.

### partially_supported

Part of the claim is supported but another part is not.

### contradicted

Available evidence conflicts with the claim.

### unsupported

No sufficient evidence was found.

### unclear

The claim cannot be interpreted with enough confidence.

### not_checkable

The claim cannot reasonably be verified.

---

# 18. Example Fact Check

Input:

```text
Our model achieved 95% accuracy.
```

Evidence:

```text
Validation accuracy = 91.8%
```

Output:

```json
{
  "claim_id": "CLM-0001",
  "status": "contradicted",
  "confidence": 0.97,
  "evidence": {
    "value": "91.8%",
    "source": "model_evaluation.json"
  },
  "correction": "The reported validation accuracy is 91.8%, not 95%."
}
```

---

# 19. Correction Generation

When a claim is incorrect, the system should generate a correction.

The correction should be based on evidence.

Bad:

```text
This claim is wrong.
```

Better:

```text
The reported accuracy is incorrect. The evaluation results show
91.8% validation accuracy rather than 95%.
```

The system should avoid inventing corrections.

If the correct value is unknown:

```text
No verified value was found in the available evidence.
```

---

# 20. Slide-Level Error Reporting

Every problem must point to its slide.

Example:

```json
{
  "slide_number": 8,
  "issue_count": 2,
  "issues": [
    {
      "claim_id": "CLM-0012",
      "severity": "high",
      "status": "contradicted",
      "claim": "The model achieved 99% accuracy.",
      "correction": "The verified accuracy is 94.2%."
    }
  ]
}
```

This allows the reviewer to open the presentation and immediately find the problem.

---

# 21. Severity

Recommended severity levels:

```text
critical
high
medium
low
```

Examples:

### Critical

A major fabricated performance result.

```text
Accuracy claimed = 99.9%
Verified accuracy = 62%
```

### High

A significant technical contradiction.

```text
Claimed algorithm = Transformer
Actual implementation = Random Forest
```

### Medium

A technical detail is incorrect.

### Low

Minor wording or non-critical unsupported statement.

---

# 22. Presentation Score

The system should calculate multiple scores instead of relying on one number.

Recommended:

```text
Overall Score
Fact Accuracy Score
Evidence Coverage Score
Claim Reliability Score
```

Example:

```json
{
  "scores": {
    "overall": 82,
    "fact_accuracy": 85,
    "evidence_coverage": 78,
    "claim_reliability": 83
  }
}
```

---

# 23. Suggested Scoring Model

A starting scoring model:

```text
Overall Score =
    0.50 × Fact Accuracy
  + 0.25 × Evidence Coverage
  + 0.25 × Claim Reliability
```

This is a starting point.

The weights should be adjusted after testing the system against manually reviewed presentations.

---

# 24. Claim-Level Scoring

Each claim can receive a score.

Example:

```text
supported             = 1.00
partially_supported   = 0.70
unclear                = 0.50
unsupported            = 0.30
contradicted           = 0.00
not_checkable          = excluded
```

The system should also consider claim importance.

A wrong high-impact performance claim should affect the score more than a minor unsupported statement.

---

# 25. Example Score

Suppose the presentation contains:

```text
10 high-impact claims
10 medium-impact claims
5 low-impact claims
```

If the applicant gets:

```text
8 high claims supported
8 medium claims supported
4 low claims supported
```

the score should be weighted by importance.

This prevents an applicant from getting a high score because many low-impact statements were correct while important technical claims were wrong.

---

# 26. Recommended Output Structure

The main API response should look like:

```json
{
  "status": "completed",

  "presentation": {
    "filename": "applicant_presentation.pptx",
    "slide_count": 12
  },

  "scores": {
    "overall": 82,
    "fact_accuracy": 85,
    "evidence_coverage": 78,
    "claim_reliability": 83
  },

  "summary": {
    "total_claims": 24,
    "supported": 17,
    "partially_supported": 2,
    "contradicted": 3,
    "unsupported": 2,
    "unclear": 0
  },

  "slides": [],

  "claims": [],

  "issues": []
}
```

---

# 27. Full Claim Output

Example:

```json
{
  "claim_id": "CLM-0015",
  "slide_number": 8,

  "claim": {
    "text": "Our model achieved 95% accuracy.",
    "type": "performance",
    "importance": "high"
  },

  "verification": {
    "status": "contradicted",
    "confidence": 0.97,

    "evidence": [
      {
        "source_type": "project_artifact",
        "source": "evaluation_results.json",
        "text": "Validation accuracy: 91.8%"
      }
    ]
  },

  "correction": {
    "text": "The verified validation accuracy is 91.8%, not 95%."
  },

  "score": 0.0,

  "severity": "high"
}
```

---

# 28. Final Report

The system should produce a human-readable report in addition to JSON.

Example:

```text
Applicant Presentation Analysis

Overall Score: 82/100

Slides Analyzed: 12
Claims Identified: 24

Supported Claims: 17
Partially Supported: 2
Contradicted: 3
Unsupported: 2

Issues

Slide 8
High severity

Claim:
"Our model achieved 95% accuracy."

Status:
Contradicted

Verified Value:
91.8%

Suggested Correction:
"The model achieved 91.8% validation accuracy."

------------------------------------------------

Slide 10
Medium severity

Claim:
"The system works completely offline."

Status:
Unsupported

No evidence was found confirming offline operation.
```

---

# 29. Internal Architecture

Recommended architecture:

```text
                    API
                     │
                     ▼
              Presentation Service
                     │
       ┌─────────────┼─────────────┐
       ▼             ▼             ▼
   Extraction    Claim Engine   File Manager
       │             │
       ▼             ▼
    Cleaner      Normalizer
                     │
                     ▼
              Evidence Engine
                     │
                     ▼
             Fact Checker
                     │
                     ▼
                Scoring
                     │
                     ▼
              Report Builder
                     │
                     ▼
                  JSON
```

---

# 30. Suggested Project Structure

```text
applicant-presentation-ai/
│
├── app/
│   ├── api/
│   │   ├── routes.py
│   │   └── schemas.py
│   │
│   ├── extraction/
│   │   ├── pptx_extractor.py
│   │   ├── table_extractor.py
│   │   ├── image_extractor.py
│   │   └── normalizer.py
│   │
│   ├── claims/
│   │   ├── extractor.py
│   │   ├── classifier.py
│   │   └── normalizer.py
│   │
│   ├── evidence/
│   │   ├── retriever.py
│   │   ├── ranking.py
│   │   └── sources.py
│   │
│   ├── fact_checking/
│   │   ├── verifier.py
│   │   ├── contradiction.py
│   │   └── confidence.py
│   │
│   ├── scoring/
│   │   ├── claim_score.py
│   │   └── presentation_score.py
│   │
│   ├── reporting/
│   │   ├── json_report.py
│   │   └── text_report.py
│   │
│   └── config/
│       └── settings.py
│
├── tests/
│   ├── extraction/
│   ├── claims/
│   ├── fact_checking/
│   └── scoring/
│
├── data/
│   ├── test_presentations/
│   └── evidence/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PIPELINE.md
│   └── SCORING.md
│
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

# 31. AI Components

The system does not need one model for everything.

A better architecture separates responsibilities.

## LLM

Use the LLM for:

* Claim extraction
* Claim classification
* Claim normalization
* Reasoning over evidence
* Generating explanations
* Generating corrections

## Embedding Model

Use embeddings for:

* Semantic search
* Evidence retrieval
* Claim-to-evidence matching
* Later Presentation-to-Demo matching

## OCR / Vision Model

Use only when needed for:

* Text inside images
* Charts
* Architecture diagrams
* Screenshots
* Image-based tables

---

# 32. Deterministic vs AI Processing

Not every component should use AI.

Use deterministic code for:

```text
PPTX parsing
Slide numbering
Text extraction
Table extraction
File validation
JSON validation
Score calculation
```

Use AI for:

```text
Claim extraction
Claim classification
Semantic interpretation
Fact-check reasoning
Correction generation
```

This makes the system easier to test and reduces unnecessary model calls.

---

# 33. Claim Normalization

A claim should have a normalized representation.

Example:

Original:

```text
Our model achieved an accuracy of 95%.
```

Normalized:

```json
{
  "subject": "model",
  "property": "accuracy",
  "value": 95,
  "unit": "%",
  "claim_type": "performance"
}
```

This becomes important later when comparing the presentation with the demo.

For example:

Presentation:

```json
{
  "property": "accuracy",
  "value": 95
}
```

Demo:

```json
{
  "property": "accuracy",
  "value": 87
}
```

The integration layer can then detect a contradiction.

---

# 34. Future Presentation-Demo Integration

The Presentation AI output should be designed for future integration.

The most important object is the normalized claim.

Example:

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

The Demo AI system can produce a similar object:

```json
{
  "claim_id": "DCLM-021",
  "subject": "model",
  "property": "accuracy",
  "value": 87,
  "unit": "%",
  "timestamp": 324.5,
  "speaker": "Applicant"
}
```

The integration layer can compare them.

---

# 35. Presentation-Demo Relationship Types

The future integration system should classify relationships as:

```text
consistent
contradicted
additional
missing
unrelated
```

Example:

```text
Presentation:
"The model achieved 95% accuracy."

Demo:
"The model achieved 95% accuracy."

Relationship:
consistent
```

Example:

```text
Presentation:
"The model achieved 95% accuracy."

Demo:
"The model achieved 87% accuracy."

Relationship:
contradicted
```

Example:

```text
Presentation:
"The model uses Random Forest."

Demo:
"The model uses Random Forest with 15 features."

Relationship:
additional
```

---

# 36. API Design

Recommended endpoints:

```text
POST /api/v1/presentation/analyze
```

Analyze a presentation.

```text
GET /api/v1/presentation/{analysis_id}
```

Retrieve an existing analysis.

```text
GET /api/v1/presentation/{analysis_id}/claims
```

Retrieve extracted claims.

```text
GET /api/v1/presentation/{analysis_id}/issues
```

Retrieve detected issues.

```text
GET /api/v1/presentation/{analysis_id}/report
```

Retrieve the final report.

---

# 37. Error Handling

The API should return structured errors.

Example:

```json
{
  "status": "error",
  "error": {
    "code": "EXTRACTION_FAILED",
    "message": "Unable to extract content from the presentation."
  }
}
```

Recommended error codes:

```text
INVALID_FILE
UNSUPPORTED_FORMAT
FILE_TOO_LARGE
CORRUPTED_FILE
EXTRACTION_FAILED
CLAIM_EXTRACTION_FAILED
FACT_CHECK_FAILED
SCORING_FAILED
INTERNAL_ERROR
```

---

# 38. Confidence

Every AI-generated decision should have a confidence value where possible.

Example:

```json
{
  "status": "contradicted",
  "confidence": 0.94
}
```

Confidence should not be treated as absolute truth.

It helps the downstream system decide when human review is needed.

---

# 39. Human Review

The system should support human review.

For example:

```text
High confidence contradiction
        ↓
Automatically reported

Low confidence contradiction
        ↓
Human review
```

A reviewer should be able to see:

```text
Slide
Claim
Evidence
Decision
Confidence
Correction
```

This creates an auditable process.

---

# 40. Important Design Principle

The system should separate:

```text
What the applicant said
```

from:

```text
What the evidence says
```

And then:

```text
System decision
```

should come after both.

Example:

```text
Applicant Claim
      │
      ▼
Evidence
      │
      ▼
Comparison
      │
      ▼
Decision
```

Do not let the LLM simply decide whether a statement is true without showing the evidence used for the decision.

---

# 41. MVP

The first version should stay focused.

MVP:

```text
PPTX upload
     ↓
Text extraction
     ↓
Slide-aware content
     ↓
Claim extraction
     ↓
Claim classification
     ↓
Evidence retrieval
     ↓
Fact checking
     ↓
Correction generation
     ↓
Score
     ↓
JSON report
```

The MVP does not need:

* Complex image understanding
* Video integration
* Advanced charts analysis
* Multi-agent architecture
* Complex frontend
* Fine-tuning
* Real-time processing

---

# 42. Phase 2

After the MVP works:

```text
Image extraction
        ↓
OCR
        ↓
Vision analysis
        ↓
Chart understanding
        ↓
Diagram understanding
```

Then improve evidence retrieval:

```text
Hybrid Search
    │
    ├── Keyword Search
    └── Vector Search
```

Then improve scoring and evaluation.

---

# 43. Phase 3

Integrate with Applicant Demo AI.

```text
Presentation AI
      │
      ▼
Presentation Claims
      │
      ├───────────────┐
      │               │
      ▼               ▼
Presentation       Demo AI
                   Claims
      │               │
      └───────┬───────┘
              ▼
      Consistency Engine
              │
              ▼
         Final Score
```

---

# 44. Testing Strategy

The project should have several levels of testing.

## Unit Tests

Test:

```text
PPTX extraction
Text normalization
Claim parsing
Score calculation
JSON validation
```

## Integration Tests

Test:

```text
PPTX
 ↓
Extraction
 ↓
Claims
 ↓
Fact checking
 ↓
Score
```

## Evaluation Dataset

Create a set of presentations with manually labeled claims.

Example:

```text
Presentation 01
20 claims

Supported = 12
Contradicted = 4
Unsupported = 4
```

The AI output can then be compared against the human labels.

---

# 45. Evaluation Metrics

Measure:

## Claim Extraction

```text
Precision
Recall
F1-score
```

## Fact Checking

Measure:

```text
Accuracy
Precision
Recall
F1-score
```

## Contradiction Detection

Measure:

```text
Precision
Recall
F1-score
```

## Numerical Claims

Measure:

```text
Exact value accuracy
Tolerance-based accuracy
```

For example:

```text
Claimed: 95%
Verified: 94.8%
```

A configurable tolerance can determine whether this is considered consistent.

---

# 46. Observability

The system should log:

```text
analysis_id
file
processing time
number of slides
number of claims
model calls
failed claims
fact-check results
final score
```

Avoid storing unnecessary sensitive applicant information in logs.

---

# 47. Performance

The pipeline should avoid unnecessary LLM calls.

For example:

```text
Slide extraction
    ↓
Local processing
    ↓
Claim detection
    ↓
Only factual claims
    ↓
Fact checking
```

Do not send every PowerPoint sentence to an expensive model.

Caching can also be used.

If the same content appears again, the system should avoid repeating expensive processing where possible.

---

# 48. Security

The presentation is an untrusted input.

The system should:

* Validate file types
* Limit file size
* Sanitize extracted content
* Avoid executing embedded files
* Isolate document processing
* Apply request limits
* Avoid exposing internal evidence sources
* Protect applicant data
* Avoid logging raw presentation content unnecessarily

---

# 49. Final Output Contract

The final response should always contain:

```text
analysis_id
status
presentation metadata
scores
claim summary
claims
issues
```

Example:

```json
{
  "analysis_id": "ANL-20260828-001",

  "status": "completed",

  "presentation": {
    "filename": "candidate_demo.pptx",
    "slide_count": 15
  },

  "scores": {
    "overall": 84,
    "fact_accuracy": 87,
    "evidence_coverage": 80,
    "claim_reliability": 84
  },

  "summary": {
    "total_claims": 31,
    "supported": 24,
    "partially_supported": 2,
    "contradicted": 3,
    "unsupported": 2,
    "unclear": 0
  },

  "claims": [],

  "issues": []
}
```

---

# 50. Definition of Done

The MVP is considered complete when the system can:

* Accept a `.pptx` file.
* Validate the file.
* Extract slide content.
* Preserve slide numbers.
* Extract tables.
* Normalize extracted content.
* Identify factual claims.
* Classify claims.
* Retrieve relevant evidence.
* Determine claim status.
* Distinguish contradicted from unsupported claims.
* Generate evidence-based corrections.
* Assign severity.
* Calculate a presentation score.
* Return structured JSON.
* Generate a human-readable report.
* Preserve normalized claims for future Demo AI integration.
* Pass the project's evaluation dataset.

---

# 51. Final Architecture

The target architecture is:

```text
                  Applicant
                     │
                     ▼
              Presentation.pptx
                     │
                     ▼
             ┌───────────────┐
             │ File Validator│
             └───────┬───────┘
                     │
                     ▼
             ┌───────────────┐
             │ PPTX Extractor│
             └───────┬───────┘
                     │
                     ▼
             ┌───────────────┐
             │  Normalizer   │
             └───────┬───────┘
                     │
                     ▼
             ┌───────────────┐
             │Claim Extraction│
             └───────┬───────┘
                     │
                     ▼
             ┌───────────────┐
             │Claim Normalize│
             └───────┬───────┘
                     │
                     ▼
             ┌───────────────┐
             │Evidence Search│
             └───────┬───────┘
                     │
                     ▼
             ┌───────────────┐
             │ Fact Checking │
             └───────┬───────┘
                     │
                     ▼
             ┌───────────────┐
             │    Scoring    │
             └───────┬───────┘
                     │
             ┌───────┴────────┐
             ▼                ▼
       JSON Report       Human Report
             │
             ▼
       Presentation Claims
             │
             ▼
       Future Demo AI
             │
             ▼
    Presentation-Demo Consistency
```

---

# 52. Project Goal

The final goal of Applicant Presentation AI is not simply to determine whether a PowerPoint presentation looks good.

The system should answer:

```text
What did the applicant claim?

Where did they claim it?

Can the claim be verified?

What evidence supports or contradicts it?

How reliable is the presentation?

What claims require attention?

What is the applicant's overall presentation accuracy?
```

The output then becomes a trusted input for the next stage of the HR evaluation pipeline.

```text
Presentation AI
       +
Demo AI
       ↓
Consistency Analysis
       ↓
Final Applicant Evaluation
```

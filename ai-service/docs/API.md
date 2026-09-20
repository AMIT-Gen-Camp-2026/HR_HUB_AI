# REST API Reference

The AI Service exposes a Flask REST API for CV parsing, structured candidate data extraction, and capability ranking.

---

## 1. Authentication

When `AI_SERVICE_API_KEY` is configured in `.env`, requests to `/api/v1/cv/evaluate` must include the following header:

- `X-API-Key: <AI_SERVICE_API_KEY>`

Authentication is enforced via constant-time string comparison (`hmac.compare_digest`). If `AI_SERVICE_API_KEY` is unset or empty, authentication is disabled and a warning is logged once. `/api/v1/health` is always public.

---

## 2. Endpoints

### A. `GET /api/v1/health`
Health check endpoint reporting service status.

#### Response (`200 OK`):
```json
{
  "status": "ok"
}
```

---

### B. `POST /api/v1/cv/evaluate`
Extracts structured candidate data from an uploaded CV file and ranks candidate capabilities against a Job Description.

#### Request Headers:
- `Content-Type: multipart/form-data`
- `X-API-Key: <AI_SERVICE_API_KEY>` (if configured)

#### Request Parameters (Multipart Form Data):
| Parameter | Type | Required | Description |
|---|---|---|---|
| `file` | File Binary | **Yes** | CV document (`.pdf` or `.docx`, maximum `10MB`). |
| `job_description` | JSON String | **Yes** | JSON-encoded string representing a `JobDescription` object. |

#### `JobDescription` Schema Fields:
| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `title` | String | **Yes** | — | Target job title. |
| `required_skills` | List[String] | **Yes** | — | Mandatory skills required for the role. |
| `required_skill_groups` | List[List[String]] | No | `null` | Optional mutually-alternative skill groups (satisfying any one fulfills the group requirement). |
| `nice_to_have_skills` | List[String] | No | `[]` | Preferred qualifications and secondary skills. |
| `min_experience_years` | Integer | No | `null` | Minimum years of professional experience. |
| `matching_mode` | String (`"taxonomy"` \| `"semantic"`) | No | `"taxonomy"` | Matching engine mode: `"taxonomy"` for strict taxonomy-gated matching with source multipliers, or `"semantic"` for LLM requirement intent enrichment with direct capability judgment. |

#### Example `job_description` JSON payload (Taxonomy Mode — Default):
```json
{
  "title": "Junior QA Engineer",
  "matching_mode": "taxonomy",
  "required_skills": [
    "Selenium WebDriver",
    "Postman",
    "SQL (SELECT, JOINs, WHERE clauses)",
    "Jira",
    "Object-Oriented Programming (Java or Python)",
    "Software Development Life Cycle (SDLC)",
    "Software Testing Life Cycle (STLC)"
  ],
  "nice_to_have_skills": [
    "ISTQB Certified Tester Foundation Level (CTFL)",
    "TestNG",
    "JUnit",
    "Cucumber (BDD)"
  ],
  "min_experience_years": 0
}
```

#### Example cURL Request (Taxonomy Mode):
```bash
curl -X POST http://localhost:5000/api/v1/cv/evaluate \
  -H "X-API-Key: secret-key-here" \
  -F "file=@/path/to/candidate_cv.pdf" \
  -F 'job_description={"title":"Junior QA Engineer","matching_mode":"taxonomy","required_skills":["Selenium WebDriver","Postman","SQL (SELECT, JOINs, WHERE clauses)","Jira","Object-Oriented Programming (Java or Python)","Software Development Life Cycle (SDLC)","Software Testing Life Cycle (STLC)"],"nice_to_have_skills":["ISTQB Certified Tester Foundation Level (CTFL)","TestNG","JUnit","Cucumber (BDD)"],"min_experience_years":0}'
```

#### Example `job_description` JSON payload (Semantic Mode):
```json
{
  "title": "Software Tester",
  "matching_mode": "semantic",
  "required_skills": [
    "Manual Testing",
    "Automated Testing",
    "API Testing",
    "Problem Solving"
  ],
  "nice_to_have_skills": [
    "Performance Testing",
    "Security Testing"
  ],
  "min_experience_years": 1
}
```

#### Example cURL Request (Semantic Mode):
```bash
curl -X POST http://localhost:5000/api/v1/cv/evaluate \
  -H "X-API-Key: secret-key-here" \
  -F "file=@/path/to/candidate_cv.pdf" \
  -F 'job_description={"title":"Software Tester","matching_mode":"semantic","required_skills":["Manual Testing","Automated Testing","API Testing","Problem Solving"],"nice_to_have_skills":["Performance Testing","Security Testing"],"min_experience_years":1}'
```

---

## 3. Success Response (`200 OK`)

```json
{
  "success": true,
  "cv": {
    "personal_info": {
      "full_name": "Mohamed Galal",
      "email": "mohamed@example.com",
      "phone": "01012345678",
      "location": "Cairo, Egypt",
      "linkedin": null,
      "github": null
    },
    "education": [],
    "skills": [
      "Software testing",
      "API testing",
      "Manual testing",
      "Database testing",
      "Team collaboration",
      "Communication skills",
      "Time management",
      "Communication",
      "Automation testing",
      "Test case design",
      "Software debugging",
      "JIRA management"
    ],
    "inferred_skills": [],
    "certifications": [
      "ISTQB® Certified CTFL V4 certified."
    ],
    "experience": [
      {
        "job_title": "Software Tester Trainee",
        "company": "DEPI",
        "start_date": "11/2025",
        "end_date": "07/2026",
        "description": "Executed manual testing procedures for thorough evaluation of software functionality. Performed API testing to confirm seamless integration between applications. Implemented basic automation testing to enhance testing efficiency. Carried out database testing to ensure data integrity and optimize performance."
      },
      {
        "job_title": "Software Testing Diploma Student",
        "company": "AMIT",
        "start_date": "10/2025",
        "end_date": "05/2026",
        "description": "Performed API testing to verify functionality and performance of integrations. Conducted manual testing on software applications, identifying defects to enhance product quality. Conducted database testing to validate data integrity and performance. Implemented basic automation testing processes, streamlining testing efforts for increased accuracy."
      }
    ],
    "projects": []
  },
  "ranking": {
    "score": 33.6,
    "candidate_id": null,
    "judge_provider": "gemini",
    "judge_model": "gemini-3.8-flash",
    "semantic_fit": null,
    "skill_evaluations": [
      {
        "requirement": "Selenium WebDriver",
        "satisfaction_percent": 20.0,
        "reasoning": "The candidate notes 'Automation testing' and implementing basic automation testing, but Selenium WebDriver is never explicitly mentioned.",
        "evidence_quote": "Implemented basic automation testing to enhance testing efficiency.",
        "source_multiplier": 0.8,
        "final_skill_score": 16.0
      },
      {
        "requirement": "Postman",
        "satisfaction_percent": 25.0,
        "reasoning": "The candidate has experience performing API testing across multiple roles, but Postman as a specific tool is not mentioned.",
        "evidence_quote": "Performed API testing to confirm seamless integration between applications.",
        "source_multiplier": 0.8,
        "final_skill_score": 20.0
      },
      {
        "requirement": "SQL (SELECT, JOINs, WHERE clauses)",
        "satisfaction_percent": 20.0,
        "reasoning": "The candidate mentions database testing to validate data integrity, but does not provide explicit evidence of SQL or specific clauses like SELECT, JOINs, and WHERE.",
        "evidence_quote": "Carried out database testing to ensure data integrity and optimize performance.",
        "source_multiplier": 0.5,
        "final_skill_score": 10.0
      },
      {
        "requirement": "Jira",
        "satisfaction_percent": 95.0,
        "reasoning": "The candidate directly lists JIRA management as an explicit skill.",
        "evidence_quote": "Explicit skill: JIRA management",
        "source_multiplier": 1.0,
        "final_skill_score": 95.0
      },
      {
        "requirement": "Object-Oriented Programming (Java or Python)",
        "satisfaction_percent": 0.0,
        "reasoning": "There is no mention of Object-Oriented Programming, Java, or Python in the candidate's profile.",
        "evidence_quote": "",
        "source_multiplier": 0.5,
        "final_skill_score": 0.0
      },
      {
        "requirement": "Software Development Life Cycle (SDLC)",
        "satisfaction_percent": 30.0,
        "reasoning": "The candidate holds an ISTQB CTFL certification and software testing diploma which cover SDLC concepts, but SDLC is not explicitly cited or detailed in practical operations.",
        "evidence_quote": "Certification: ISTQB® Certified CTFL V4 certified.",
        "source_multiplier": 0.5,
        "final_skill_score": 15.0
      },
      {
        "requirement": "Software Testing Life Cycle (STLC)",
        "satisfaction_percent": 60.0,
        "reasoning": "The candidate demonstrates practical coverage of core STLC phases, including test case design, manual execution, defect identification, and certification under ISTQB CTFL.",
        "evidence_quote": "Conducted manual testing on software applications, identifying defects to enhance product quality.",
        "source_multiplier": 0.5,
        "final_skill_score": 30.0
      },
      {
        "requirement": "ISTQB Certified Tester Foundation Level (CTFL)",
        "satisfaction_percent": 100.0,
        "reasoning": "The candidate holds the exact ISTQB CTFL V4 certification.",
        "evidence_quote": "Certification: ISTQB® Certified CTFL V4 certified.",
        "source_multiplier": 1.0,
        "final_skill_score": 100.0
      },
      {
        "requirement": "TestNG",
        "satisfaction_percent": 0.0,
        "reasoning": "There is no evidence mentioning TestNG or its usage.",
        "evidence_quote": "",
        "source_multiplier": 0.8,
        "final_skill_score": 0.0
      },
      {
        "requirement": "JUnit",
        "satisfaction_percent": 0.0,
        "reasoning": "There is no evidence mentioning JUnit.",
        "evidence_quote": "",
        "source_multiplier": 0.8,
        "final_skill_score": 0.0
      },
      {
        "requirement": "Cucumber (BDD)",
        "satisfaction_percent": 0.0,
        "reasoning": "There is no mention of Cucumber or Behavior-Driven Development (BDD).",
        "evidence_quote": "",
        "source_multiplier": 0.5,
        "final_skill_score": 0.0
      }
    ],
    "breakdown": {
      "scoring_version": "weighted-70-20-10-v1",
      "required_component": 0.186,
      "nice_to_have_component": 0.05,
      "experience_component": 0.1,
      "candidate_total_years": 1.24,
      "experience_ratio": 1.0,
      "required_skills_total": 7,
      "required_satisfaction_average": 0.3571,
      "nice_to_have_skills_total": 4,
      "nice_to_have_satisfaction_average": 0.25,
      "preferred_bonus": 0.0321,
      "hard_skill_score": 0.3893,
      "hard_skill_weight": 1.0,
      "semantic_weight": 0.0,
      "taxonomy_version": "2026.09",
      "judge_prompt_version": "ranking-judge-v1"
    }
  },
  "extraction_status": "OK",
  "extraction_metadata": {
    "model_repo_id": "Qwen/Qwen2.5-3B-Instruct",
    "model_provider": "featherless-ai"
  }
}
```

---

## 4. HTTP Status Codes & Error Responses

When a request fails, the API returns a JSON object with `"success": false` and an `"error"` message.

```json
{
  "success": false,
  "error": "Detailed error description"
}
```

| HTTP Status | Code Location | Trigger Condition | Exact Response Body |
|---|---|---|---|
| `400 Bad Request` | `app/main.py:L63` | Missing `file` field in form-data | `{"success": false, "error": "No 'file' field in form-data."}` |
| `400 Bad Request` | `app/main.py:L67` | No file selected / empty filename | `{"success": false, "error": "No file selected."}` |
| `400 Bad Request` | `app/main.py:L71` | Missing `job_description` field | `{"success": false, "error": "Missing 'job_description' field in form-data."}` |
| `400 Bad Request` | `app/main.py:L76` | `job_description` not valid JSON | `{"success": false, "error": "job_description must be valid JSON."}` |
| `400 Bad Request` | `app/main.py:L79` | `job_description` not a JSON object | `{"success": false, "error": "job_description must be a JSON object."}` |
| `400 Bad Request` | `app/main.py:L89` | Extension not `.pdf` or `.docx` | `{"success": false, "error": "File extension not allowed: <ext>"}` |
| `400 Bad Request` | `app/main.py:L100` | Header bytes mismatch expected format | `{"success": false, "error": "File content does not match extension..."}` |
| `401 Unauthorized` | `app/security/auth.py:L50` | Missing or invalid `X-API-Key` | `{"success": false, "error": "Missing or invalid API key."}` |
| `413 Payload Too Large` | `app/main.py:L45` | File size exceeds `MAX_CONTENT_LENGTH` (`10MB`) | Standard WSGI 413 response |
| `422 Unprocessable Entity`| `app/main.py:L84` | `job_description` fails Pydantic validation | `{"success": false, "error": [{"loc": ["required_skills"], ...}]}` |
| `422 Unprocessable Entity`| `app/main.py:L104` | No extractable text extracted from file | `{"success": false, "error": "No extractable text found in file."}` |
| `429 Too Many Requests` | `app/main.py:L60` | Request rate exceeds limit (`10 per hour`) | `{"message": "10 per 1 hour"}` |
| `502 Bad Gateway` | `app/main.py:L116` | Extraction inference failed across model chain | `{"success": false, "error": "Model inference failed. Please try again.", "extraction_status": "FAILED"}` |
| `502 Bad Gateway` | `app/main.py:L151` | Judge evaluation failed across provider chain | `{"success": false, "error": "Ranking model inference failed. Please try again."}` |
| `500 Internal Server Error`| `app/main.py:L154, L168`| Uncaught server exception | `{"success": false, "error": "Internal server error."}` |

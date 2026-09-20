"""
Live reproducibility test runner for Semantic Matching Mode against Groq.
Executes 6 live unmocked runs against the real Groq API.
"""
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from config.settings import config
from app import main
from app.pipeline import run as pipeline_run
from app.pipeline import ranking as pipeline_ranking
from app.providers import judge_provider

def run_reproducibility_test(num_runs: int = 6):
    print(f"=== Starting Task 5: Live Reproducibility Test ({num_runs} runs) ===")
    print(f"Groq API Key Present: {bool(config.GROQ_API_KEY)}")
    print(f"Groq Judge Model: {config.GROQ_JUDGE_MODEL}")
    print(f"Groq Base URL: {config.GROQ_BASE_URL}")
    
    if not config.GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set in .env! Cannot run live Groq test.")

    # Configure judge chain to force Groq as primary
    def groq_primary_judge_chain():
        providers = []
        providers.append(
            judge_provider.OpenAICompatibleJudgeProvider(
                "groq",
                config.GROQ_JUDGE_MODEL,
                config.GROQ_API_KEY,
                config.GROQ_BASE_URL,
            )
        )
        if config.GEMINI_API_KEY:
            providers.append(
                judge_provider.GeminiJudgeProvider(config.GEMINI_API_KEY, config.GEMINI_JUDGE_MODEL)
            )
        if config.OPENROUTER_API_KEY:
            providers.append(
                judge_provider.OpenAICompatibleJudgeProvider(
                    "openrouter",
                    config.OPENROUTER_JUDGE_MODEL,
                    config.OPENROUTER_API_KEY,
                    config.OPENROUTER_BASE_URL,
                    {"HTTP-Referer": config.OPENROUTER_SITE_URL, "X-Title": "HR Hub AI"},
                )
            )
        return providers

    judge_provider.configured_judge_chain = groq_primary_judge_chain

    # Disable flask rate limiter for test
    main.limiter.enabled = False
    main.config.RANKING_ENABLED = True
    main.config.AI_SERVICE_API_KEY = ""

    client = main.app.test_client()

    import io
    # Load candidate PDF
    cv_pdf_path = PROJECT_ROOT / "data" / "680f0d3de7b54d7db486d468bc9e7420_Osama_Adel.pdf"
    if not cv_pdf_path.exists():
        raise FileNotFoundError(f"Candidate CV not found at: {cv_pdf_path}")

    with open(cv_pdf_path, "rb") as f:
        pdf_bytes = f.read()

    # Reference QA JD
    jd_payload = {
        "title": "Junior QA Engineer",
        "required_skills": [
            "Selenium WebDriver",
            "Postman",
            "SQL (SELECT, JOINs, WHERE clauses)",
            "Jira",
            "Object-Oriented Programming (Java or Python)",
            "Software Development Life Cycle (SDLC)",
            "Software Testing Life Cycle (STLC)",
        ],
        "nice_to_have_skills": [
            "ISTQB Certified Tester Foundation Level (CTFL)",
            "TestNG",
            "JUnit",
            "Cucumber (BDD)",
        ],
        "min_experience_years": 0,
        "matching_mode": "semantic",
    }

    results = []

    for run_idx in range(1, num_runs + 1):
        print(f"\n--- Running Iteration {run_idx}/{num_runs} ---")
        
        # Clear ranking cache to ensure every run queries the real judge over the network
        pipeline_run._ranking_cache.clear()
        
        start_time = time.perf_counter()
        
        response = client.post(
            "/api/v1/cv/evaluate",
            data={
                "file": (io.BytesIO(pdf_bytes), "Osama_Adel.pdf", "application/pdf"),
                "job_description": json.dumps(jd_payload),
            },
            content_type="multipart/form-data",
        )
        
        latency = time.perf_counter() - start_time
        
        print(f"Status Code: {response.status_code}, Latency: {latency:.2f}s")
        if response.status_code != 200:
            print(f"Error Response: {response.get_data(as_text=True)}")
            results.append({
                "run_index": run_idx,
                "status_code": response.status_code,
                "error": response.get_data(as_text=True),
                "latency_sec": round(latency, 3),
            })
            continue

        data = response.get_json()
        ranking = data.get("ranking", {})
        
        run_record = {
            "run_index": run_idx,
            "status_code": response.status_code,
            "latency_sec": round(latency, 3),
            "score": ranking.get("score"),
            "judge_provider": ranking.get("judge_provider"),
            "judge_model": ranking.get("judge_model"),
            "fallback_to_taxonomy": ranking.get("breakdown", {}).get("fallback_to_taxonomy"),
            "breakdown": ranking.get("breakdown"),
            "skill_evaluations": ranking.get("skill_evaluations", []),
        }
        
        print(f"Score: {run_record['score']}, Provider: {run_record['judge_provider']}, Model: {run_record['judge_model']}, Fallback: {run_record['fallback_to_taxonomy']}")
        results.append(run_record)

        if run_idx < num_runs:
            time.sleep(2.0)  # Rate limit courtesy spacing

    # Save results
    output_dir = PROJECT_ROOT / "scratch"
    output_dir.mkdir(exist_ok=True)
    out_file = output_dir / "reproducibility_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(results)} run results to {out_file}")
    return results

if __name__ == "__main__":
    run_reproducibility_test(6)

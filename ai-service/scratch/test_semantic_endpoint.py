import json
from app.main import app
from config.settings import config

def main():
    client = app.test_client()
    cv_path = "data/680f0d3de7b54d7db486d468bc9e7420_Osama_Adel.pdf"
    jd = {
        "title": "Software Tester",
        "required_skills": ["Manual Testing", "Automated Testing", "Python"],
        "nice_to_have_skills": ["Selenium"],
        "matching_mode": "semantic",
    }
    headers = {"X-API-Key": config.AI_SERVICE_API_KEY} if config.AI_SERVICE_API_KEY else {}

    with open(cv_path, "rb") as f:
        data = {
            "file": (f, "Osama_Adel.pdf"),
            "job_description": json.dumps(jd),
        }
        response = client.post(
            "/api/v1/cv/evaluate",
            headers=headers,
            data=data,
            content_type="multipart/form-data",
        )

    print("HTTP Status:", response.status_code)
    payload = response.get_json()
    print("Success:", payload.get("success"))
    ranking = payload.get("ranking", {})
    print("Score:", ranking.get("score"))
    print("Judge Provider:", ranking.get("judge_provider"))
    print("Judge Model:", ranking.get("judge_model"))
    breakdown = ranking.get("breakdown", {})
    print("Judge Prompt Version:", breakdown.get("judge_prompt_version"))
    print("Fallback to Taxonomy:", breakdown.get("fallback_to_taxonomy"))
    print("Scoring Version:", breakdown.get("scoring_version"))

if __name__ == "__main__":
    main()

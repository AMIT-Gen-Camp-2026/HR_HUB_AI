import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

results_path = Path("scratch/reproducibility_results.json")
with open(results_path, "r", encoding="utf-8") as f:
    runs = json.load(f)

print("=== RUN OVERVIEW ===")
print(f"Total Runs: {len(runs)}")
for r in runs:
    print(
        f"Run {r['run_index']}: Score={r['score']}, "
        f"Latency={r['latency_sec']}s, "
        f"Provider={r['judge_provider']}, "
        f"Model={r['judge_model']}, "
        f"FallbackToTaxonomy={r['fallback_to_taxonomy']}"
    )

scores = [r["score"] for r in runs]
print("\n=== SCORE STATS ===")
print(f"Min Score: {min(scores)}")
print(f"Max Score: {max(scores)}")
print(f"Spread (Max - Min): {round(max(scores) - min(scores), 2)}")
print(f"Mean Score: {sum(scores) / len(scores):.2f}")

groq_scores = [r["score"] for r in runs if r["judge_provider"] == "groq"]
openrouter_scores = [r["score"] for r in runs if r["judge_provider"] == "openrouter"]
print(f"Groq-only Scores (Runs 2, 4, 5): {groq_scores}, Min={min(groq_scores)}, Max={max(groq_scores)}, Spread={round(max(groq_scores) - min(groq_scores), 2)}")
print(f"OpenRouter-only Scores (Runs 1, 3, 6): {openrouter_scores}, Min={min(openrouter_scores)}, Max={max(openrouter_scores)}, Spread={round(max(openrouter_scores) - min(openrouter_scores), 2)}")

print("\n=== PER-REQUIREMENT SATISFACTION PER RUN ===")
req_names = [e["requirement"] for e in runs[0]["skill_evaluations"]]
header = " | ".join(["Requirement"] + [f"Run {r['run_index']} ({r['judge_provider'][:4]})" for r in runs])
print(header)
print("-" * len(header))
for req in req_names:
    row = [req]
    for r in runs:
        match = next(e for e in r["skill_evaluations"] if e["requirement"] == req)
        row.append(f"{match['satisfaction_percent']}%")
    print(" | ".join(row))

print("\n=== ANCHOR ADHERENCE CHECK ===")
valid_anchors = {100.0, 75.0, 50.0, 25.0, 0.0}
all_anchors_valid = True
for r in runs:
    for e in r["skill_evaluations"]:
        val = e["satisfaction_percent"]
        if val not in valid_anchors:
            print(f"INVALID ANCHOR in Run {r['run_index']}, Req {e['requirement']}: {val}")
            all_anchors_valid = False
if all_anchors_valid:
    print("ALL satisfaction_percent values across ALL 6 runs strictly adhere to the 5 allowed anchors: {100.0, 75.0, 50.0, 25.0, 0.0}")

print("\n=== EVIDENCE QUOTES PER REQUIREMENT ===")
for req in [
    "Selenium WebDriver",
    "Postman",
    "SQL (SELECT, JOINs, WHERE clauses)",
    "Object-Oriented Programming (Java or Python)",
    "Jira",
]:
    print(f"\n--- Requirement: {req} ---")
    for r in runs:
        match = next(e for e in r["skill_evaluations"] if e["requirement"] == req)
        print(f"Run {r['run_index']} ({r['judge_provider']}) [{match['satisfaction_percent']}%]: Quote: \"{match['evidence_quote']}\"")
        print(f"    Reasoning: \"{match['reasoning']}\"")

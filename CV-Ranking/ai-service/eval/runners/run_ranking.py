"""Run the ranking pipeline against a labelled human-shortlist dataset and
print one honest agreement number, compared against a naive baseline.

Metric: mean Agreement@k across job rows, where k = size of the human
shortlist for that job, and Agreement@k = |model_top_k ∩ human_shortlist| / k.
Per eval/README.md: "Ranking — Agreement with human shortlist — ≥ 70%".

Unlike run_extraction.py, this runner is fully implemented (not a TODO
stub) — rank() itself was already built and tested in Sprint 2
(app/pipeline/ranking.py, tests/unit/test_ranking.py). What's missing is
the labelled dataset, not the metric code.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.pipeline.ranking import rank
from app.schemas.cv import CVSchema, JobDescription

DATASETS = Path(__file__).resolve().parent.parent / "datasets"


def load(spec: str) -> list[dict]:
    name, version = spec.split("@")
    path = DATASETS / name / version / "labels.jsonl"
    if not path.exists() or not path.read_text().strip():
        raise SystemExit(
            f"Dataset {spec} is empty.\n"
            f"Expected labelled rows (job_description + candidates + "
            f"human_shortlist) at {path}\n\n"
            "Without it there is no number, and without a number the "
            "feature cannot be accepted at a sprint review "
            "(eval/README.md, rule 3)."
        )
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _naive_baseline_score(candidate: CVSchema, jd: JobDescription) -> int:
    """Exact, case-insensitive string match count against required_skills
    only. No canonicalisation, no weighting, no semantic_fit — this is the
    bar rank() has to beat (eval/README.md, rule 3)."""
    candidate_skills = {s.strip().lower() for s in candidate.skills + candidate.inferred_skills}
    return sum(1 for s in jd.required_skills if s.strip().lower() in candidate_skills)


def _top_k(scored: list[tuple[str, float]], k: int) -> set[str]:
    # Deterministic tie-break by candidate id, since rank() itself is
    # deterministic and the metric shouldn't introduce randomness on top.
    ordered = sorted(scored, key=lambda pair: (-pair[1], pair[0]))
    return {candidate_id for candidate_id, _ in ordered[:k]}


def _agreement_for_row(row: dict) -> tuple[float, float]:
    """Returns (model_agreement, baseline_agreement) for one job row."""
    jd = JobDescription(**row["job_description"])
    human_shortlist = set(row["human_shortlist"])
    k = len(human_shortlist)
    if k == 0:
        raise ValueError(f"Row {row.get('id')} has an empty human_shortlist.")

    model_scores: list[tuple[str, float]] = []
    baseline_scores: list[tuple[str, float]] = []
    for entry in row["candidates"]:
        candidate_id = entry["id"]
        candidate = CVSchema(**entry["candidate"])
        model_scores.append((candidate_id, rank(candidate, jd).score))
        baseline_scores.append((candidate_id, _naive_baseline_score(candidate, jd)))

    model_top_k = _top_k(model_scores, k)
    baseline_top_k = _top_k(baseline_scores, k)

    model_agreement = len(model_top_k & human_shortlist) / k
    baseline_agreement = len(baseline_top_k & human_shortlist) / k
    return model_agreement, baseline_agreement


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="name@version, e.g. ranking@v1")
    ap.add_argument("--subset", default=None, help="ci | test | val")
    ap.add_argument("--fail-under", type=float, default=None)
    args = ap.parse_args()

    rows = load(args.dataset)
    if args.subset:
        rows = [r for r in rows if r.get("split") == args.subset][
            : 10 if args.subset == "ci" else None
        ]
    if not rows:
        raise SystemExit(f"No rows for subset={args.subset!r} in {args.dataset}.")

    model_scores_all: list[float] = []
    baseline_scores_all: list[float] = []
    for row in rows:
        model_agreement, baseline_agreement = _agreement_for_row(row)
        model_scores_all.append(model_agreement)
        baseline_scores_all.append(baseline_agreement)

    model_mean = sum(model_scores_all) / len(model_scores_all)
    baseline_mean = sum(baseline_scores_all) / len(baseline_scores_all)

    print(f"rows evaluated       : {len(rows)}")
    print(f"naive baseline (mean): {baseline_mean:.2%}")
    print(f"rank() agreement     : {model_mean:.2%}")
    print(f"beats baseline       : {'yes' if model_mean > baseline_mean else 'no'}")

    # TODO: log this run to MLflow (eval/README.md rule 5) - not wired yet,
    # same gap as eval/runners/run_extraction.py.

    if args.fail_under is not None and model_mean < args.fail_under:
        raise SystemExit(
            f"rank() agreement {model_mean:.2%} is below --fail-under {args.fail_under:.2%}."
        )


if __name__ == "__main__":
    main()
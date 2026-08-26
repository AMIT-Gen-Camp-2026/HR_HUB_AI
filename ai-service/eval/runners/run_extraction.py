"""Run the extraction pipeline against a labelled dataset and print one honest number."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

DATASETS = Path(__file__).resolve().parent.parent / "datasets"


def load(spec: str) -> list[dict]:
    name, version = spec.split("@")
    path = DATASETS / name / version / "labels.jsonl"
    if not path.exists() or not path.read_text().strip():
        raise SystemExit(
            f"Dataset {spec} is empty.\n"
            f"Expected labelled examples at {path}\n\n"
            "This is the Sprint 1 deliverable. Without it there is no number, and without a "
            "number the feature cannot be accepted at a sprint review."
        )
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True, help="name@version, e.g. cv-extraction@v1")
    ap.add_argument("--subset", default=None, help="ci | test | val")
    ap.add_argument("--fail-under", type=float, default=None)
    args = ap.parse_args()

    rows = load(args.dataset)
    if args.subset:
        rows = [r for r in rows if r.get("split") == args.subset][: 10 if args.subset == "ci" else None]

    # TODO(sprint-2): run the pipeline over each row and compute:
    #   - field accuracy per field
    #   - explicit skill recall
    #   - inferred skill recall AND precision
    #   - invented skills count (from skills_must_not_appear)
    # Report against the keyword baseline. Log the run to MLflow.
    raise SystemExit("Not implemented — Sprint 2. The dataset loader and CLI are ready.")


if __name__ == "__main__":
    asyncio.run(main())

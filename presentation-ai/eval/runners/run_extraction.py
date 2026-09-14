"""Runs claim extraction, classification, and verification against every presentation
in a labeled eval dataset, and computes comprehensive evaluation metrics:
- Extraction: Precision, Recall, F1
- Classification: Track accuracy, Claim Type accuracy, Joint accuracy
- Verification: Separate Track A (Grounded) and Track B (Plausibility) accuracy
- Plausibility: False Positive Rate (FPR) and False Negative Rate (FNR)
- Token Usage: Breakdown by stage and per-presentation averages
- Full raw per-claim matches and logs saved to eval/results/

Usage:
    python eval/runners/run_extraction.py --dataset eval/datasets/presentation-extraction/v1
    python eval/runners/run_extraction.py --dataset eval/datasets/presentation-extraction/v1 --stages extraction,classification,verdict
    python eval/runners/run_extraction.py --dataset eval/datasets/presentation-extraction/v1 --prompt-version v3
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from app.pipeline import claim_extraction, extract_pptx, fact_check, normalize
from app.prompts.registry import PromptRegistry
from app.providers.factory import build_provider
from app.schemas.presentation import Claim, ClaimVerification
from app.telemetry import get_session_records, reset_session_records
from config.settings import Settings, get_settings

_WS_RE = re.compile(r"\s+")
MATCH_THRESHOLD = 0.50


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).strip().lower()
    return _WS_RE.sub(" ", text)


def _similarity(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na in nb or nb in na:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def match_claims(predicted: list[Claim], gold: list[dict]) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matches of (pred_idx, gold_idx, score) above threshold."""
    pairs: list[tuple[float, int, int]] = []
    for pi, pred in enumerate(predicted):
        for gi, g in enumerate(gold):
            score = _similarity(pred.text, g["text"])
            if score >= MATCH_THRESHOLD:
                pairs.append((score, pi, gi))
    pairs.sort(reverse=True)
    used_p: set[int] = set()
    used_g: set[int] = set()
    matches: list[tuple[int, int, float]] = []
    for score, pi, gi in pairs:
        if pi in used_p or gi in used_g:
            continue
        used_p.add(pi)
        used_g.add(gi)
        matches.append((pi, gi, score))
    return matches


def _prf(tp: int, pred_n: int, gold_n: int) -> dict[str, Any]:
    precision = tp / pred_n if pred_n else (1.0 if gold_n == 0 else 0.0)
    recall = tp / gold_n if gold_n else (1.0 if pred_n == 0 else 0.0)
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "true_positives": tp,
        "predicted_count": pred_n,
        "gold_count": gold_n,
    }


@dataclass
class MatchedClaimDetail:
    pred_text: str
    gold_text: str
    similarity: float
    pred_track: str
    gold_track: str
    track_correct: bool
    pred_type: str
    gold_type: str
    type_correct: bool
    gold_expected_status: str | None
    pred_status: str | None
    verdict_correct: bool | None


@dataclass
class FileResult:
    filename: str
    gold_n: int
    predicted_n: int
    extraction_matches: int
    type_correct: int
    track_correct: int
    both_class_correct: int
    
    # Track A (Objective)
    track_a_compared: int = 0
    track_a_correct: int = 0
    
    # Track B (Project-Specific)
    track_b_compared: int = 0
    track_b_correct: int = 0
    
    # Plausibility specific metrics
    plausibility_gold_flags: int = 0
    plausibility_true_flags: int = 0  # correctly flagged
    plausibility_false_negatives: int = 0  # gold was flagged, pred was unflagged
    plausibility_gold_unflagged: int = 0
    plausibility_false_positives: int = 0  # gold was unflagged, pred was flagged
    
    predicted_statuses: list[str] = field(default_factory=list)
    matched_details: list[MatchedClaimDetail] = field(default_factory=list)
    unmatched_predicted: list[str] = field(default_factory=list)
    unmatched_gold: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def evaluate_file(
    *,
    pptx_path: Path,
    gold_claims: list[dict],
    provider,
    prompts: PromptRegistry,
    prompt_version: str,
    stages: set[str],
) -> FileResult:
    notes: list[str] = []
    content = pptx_path.read_bytes()
    extracted = extract_pptx.extract(content)
    normalized = normalize.normalize(extracted)

    # Call claim extraction
    predicted, failed_slides = claim_extraction.extract_claims(normalized.slides, provider, prompts)
    if failed_slides:
        notes.append(f"Failed extraction on slides: {failed_slides}")

    matches = match_claims(predicted, gold_claims)
    matched_pi = {pi for pi, _, _ in matches}
    matched_gi = {gi for _, gi, _ in matches}

    type_correct = 0
    track_correct = 0
    both_class_correct = 0

    track_a_compared = 0
    track_a_correct = 0
    track_b_compared = 0
    track_b_correct = 0

    plausibility_gold_flags = 0
    plausibility_true_flags = 0
    plausibility_false_negatives = 0
    plausibility_gold_unflagged = 0
    plausibility_false_positives = 0

    predicted_statuses: list[str] = []
    by_id: dict[str, ClaimVerification] = {}

    if "verdict" in stages and predicted:
        slide_context = {s.slide_number: normalize.slide_to_prompt_text(s) for s in normalized.slides}
        verifications = fact_check.verify_claims(predicted, provider, prompts, slide_context)
        by_id = {v.claim_id: v for v in verifications}
        predicted_statuses = [v.status for v in verifications]

    matched_details: list[MatchedClaimDetail] = []

    for pi, gi, sim in matches:
        pred = predicted[pi]
        gold = gold_claims[gi]
        type_ok = pred.claim_type == gold["claim_type"]
        track_ok = pred.track == gold["track"]
        if type_ok:
            type_correct += 1
        if track_ok:
            track_correct += 1
        if type_ok and track_ok:
            both_class_correct += 1

        expected_status = gold.get("expected_status")
        ver = by_id.get(pred.claim_id)
        pred_status = ver.status if ver else None
        verdict_ok = None

        if "verdict" in stages and expected_status and pred_status:
            verdict_ok = (pred_status == expected_status)
            if gold["track"] == "objective":
                track_a_compared += 1
                if verdict_ok:
                    track_a_correct += 1
                else:
                    notes.append(f"Track A mismatch: expected={expected_status!r} pred={pred_status!r} text={pred.text[:60]!r}")
            else:
                track_b_compared += 1
                if verdict_ok:
                    track_b_correct += 1
                else:
                    notes.append(f"Track B mismatch: expected={expected_status!r} pred={pred_status!r} text={pred.text[:60]!r}")

                # Plausibility confusion metrics
                if expected_status == "plausibility_flag":
                    plausibility_gold_flags += 1
                    if pred_status == "plausibility_flag":
                        plausibility_true_flags += 1
                    else:
                        plausibility_false_negatives += 1
                elif expected_status == "project_unsupported":
                    plausibility_gold_unflagged += 1
                    if pred_status == "plausibility_flag":
                        plausibility_false_positives += 1

        matched_details.append(
            MatchedClaimDetail(
                pred_text=pred.text,
                gold_text=gold["text"],
                similarity=round(sim, 3),
                pred_track=pred.track,
                gold_track=gold["track"],
                track_correct=track_ok,
                pred_type=pred.claim_type,
                gold_type=gold["claim_type"],
                type_correct=type_ok,
                gold_expected_status=expected_status,
                pred_status=pred_status,
                verdict_correct=verdict_ok,
            )
        )

    unmatched_p = [predicted[i].text for i in range(len(predicted)) if i not in matched_pi]
    unmatched_g = [gold_claims[i]["text"] for i in range(len(gold_claims)) if i not in matched_gi]

    return FileResult(
        filename=pptx_path.name,
        gold_n=len(gold_claims),
        predicted_n=len(predicted),
        extraction_matches=len(matches),
        type_correct=type_correct,
        track_correct=track_correct,
        both_class_correct=both_class_correct,
        track_a_compared=track_a_compared,
        track_a_correct=track_a_correct,
        track_b_compared=track_b_compared,
        track_b_correct=track_b_correct,
        plausibility_gold_flags=plausibility_gold_flags,
        plausibility_true_flags=plausibility_true_flags,
        plausibility_false_negatives=plausibility_false_negatives,
        plausibility_gold_unflagged=plausibility_gold_unflagged,
        plausibility_false_positives=plausibility_false_positives,
        predicted_statuses=predicted_statuses,
        matched_details=matched_details,
        unmatched_predicted=unmatched_p,
        unmatched_gold=unmatched_g,
        notes=notes,
    )


def aggregate_token_usage(num_presentations: int) -> dict[str, Any]:
    records = get_session_records()
    by_stage: dict[str, dict[str, int]] = {}
    tot_in = 0
    tot_out = 0

    for r in records:
        stage = r.stage
        if stage not in by_stage:
            by_stage[stage] = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "total_tokens": 0}
        by_stage[stage]["calls"] += 1
        by_stage[stage]["tokens_in"] += r.tokens_in
        by_stage[stage]["tokens_out"] += r.tokens_out
        by_stage[stage]["total_tokens"] += (r.tokens_in + r.tokens_out)
        tot_in += r.tokens_in
        tot_out += r.tokens_out

    tot = tot_in + tot_out
    avg_per_pres = round(tot / num_presentations, 1) if num_presentations else 0.0

    return {
        "total_calls": len(records),
        "total_tokens_in": tot_in,
        "total_tokens_out": tot_out,
        "total_tokens": tot,
        "avg_tokens_per_presentation": avg_per_pres,
        "by_stage": by_stage,
    }


def aggregate(results: list[FileResult], stages: set[str]) -> dict[str, Any]:
    tp = sum(r.extraction_matches for r in results)
    pred_n = sum(r.predicted_n for r in results)
    gold_n = sum(r.gold_n for r in results)
    report: dict[str, Any] = {
        "extraction": _prf(tp, pred_n, gold_n),
    }

    matched = sum(r.extraction_matches for r in results)
    if "classification" in stages or "verdict" in stages:
        report["classification"] = {
            "matched_claims": matched,
            "track_accuracy": round(sum(r.track_correct for r in results) / matched, 4) if matched else 0.0,
            "claim_type_accuracy": round(sum(r.type_correct for r in results) / matched, 4) if matched else 0.0,
            "joint_type_and_track_accuracy": round(
                sum(r.both_class_correct for r in results) / matched, 4
            ) if matched else 0.0,
        }

    if "verdict" in stages:
        # Track A
        ta_comp = sum(r.track_a_compared for r in results)
        ta_corr = sum(r.track_a_correct for r in results)
        
        # Track B
        tb_comp = sum(r.track_b_compared for r in results)
        tb_corr = sum(r.track_b_correct for r in results)

        # Plausibility Error Rates
        gold_flags = sum(r.plausibility_gold_flags for r in results)
        fn = sum(r.plausibility_false_negatives for r in results)
        gold_unflags = sum(r.plausibility_gold_unflagged for r in results)
        fp = sum(r.plausibility_false_positives for r in results)

        fnr = round(fn / gold_flags, 4) if gold_flags else 0.0
        fpr = round(fp / gold_unflags, 4) if gold_unflags else 0.0

        total_comp = ta_comp + tb_comp
        total_corr = ta_corr + tb_corr

        report["verification"] = {
            "overall_accuracy": round(total_corr / total_comp, 4) if total_comp else 0.0,
            "total_compared": total_comp,
            "total_correct": total_corr,
            "track_a_objective": {
                "accuracy": round(ta_corr / ta_comp, 4) if ta_comp else 0.0,
                "compared": ta_comp,
                "correct": ta_corr,
            },
            "track_b_project_specific": {
                "accuracy": round(tb_corr / tb_comp, 4) if tb_comp else 0.0,
                "compared": tb_comp,
                "correct": tb_corr,
                "plausibility_error_analysis": {
                    "gold_flags_count": gold_flags,
                    "false_negatives": fn,
                    "false_negative_rate": fnr,
                    "gold_unflagged_count": gold_unflags,
                    "false_positives": fp,
                    "false_positive_rate": fpr,
                },
            },
            "predicted_status_histogram": _histogram(results),
        }

    report["token_usage"] = aggregate_token_usage(len(results))
    return report


def _histogram(results: list[FileResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in results:
        for status in r.predicted_statuses:
            counts[status] = counts.get(status, 0) + 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Presentation AI pipeline against labeled ground truth.")
    parser.add_argument("--dataset", required=True, help="Path to dataset directory containing labels.jsonl")
    parser.add_argument(
        "--stages",
        default="extraction,classification,verdict",
        help="Comma-separated stages: extraction,classification,verdict",
    )
    parser.add_argument("--prompt-version", default="v3", help="Prompt version for claim_extract (e.g. v1, v2, v3)")
    parser.add_argument("--limit", type=int, default=0, help="Limit evaluation to first N presentations")
    args = parser.parse_args()

    dataset_dir = Path(args.dataset)
    labels_path = dataset_dir / "labels.jsonl"
    if not labels_path.exists() or labels_path.stat().st_size == 0:
        print(f"Error: No labels found in {labels_path}")
        return

    stages = {s.strip() for s in args.stages.split(",") if s.strip()}
    presentations_dir = dataset_dir / "presentations"

    settings: Settings = get_settings()
    provider = build_provider(settings)
    prompts = PromptRegistry(settings.prompts_dir)

    reset_session_records()

    original_render = prompts.render

    def _render(name: str, version: str = "v1", **context):
        if name == "claim_extract":
            version = args.prompt_version
        return original_render(name, version=version, **context)

    prompts.render = _render  # type: ignore[method-assign]

    labeled: list[dict[str, Any]] = []
    for line in labels_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        labeled.append(json.loads(line))

    if args.limit:
        labeled = labeled[: args.limit]

    print(f"=== Running Evaluation against {len(labeled)} presentations (Stages: {','.join(sorted(stages))}) ===")
    print(f"Provider: {settings.provider} | Prompt Version: {args.prompt_version}\n")

    results: list[FileResult] = []
    for idx, row in enumerate(labeled, 1):
        filename = row["filename"]
        pptx_path = presentations_dir / filename
        if not pptx_path.exists():
            print(f"[{idx}/{len(labeled)}] SKIP missing file: {pptx_path}")
            continue

        print(f"[{idx}/{len(labeled)}] Evaluating {filename} ...")
        res = evaluate_file(
            pptx_path=pptx_path,
            gold_claims=row.get("claims") or [],
            provider=provider,
            prompts=prompts,
            prompt_version=args.prompt_version,
            stages=stages,
        )
        results.append(res)

    summary_metrics = aggregate(results, stages)

    # Save to eval/results/
    results_dir = Path("eval/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = results_dir / f"eval_run_{stamp}_{args.prompt_version}_{settings.provider}.json"

    full_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_dir),
        "provider": settings.provider,
        "prompt_version": args.prompt_version,
        "stages": sorted(stages),
        "total_presentations": len(results),
        "metrics": summary_metrics,
        "per_file_details": [asdict(r) for r in results],
    }

    out_path.write_text(json.dumps(full_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n================ EVALUATION SUMMARY ================")
    print(json.dumps(summary_metrics, ensure_ascii=False, indent=2))
    print(f"\nRaw results saved to: {out_path}")


if __name__ == "__main__":
    main()

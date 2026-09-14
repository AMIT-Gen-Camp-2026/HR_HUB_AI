"""Live evaluation script to analyze sample presentations with Gemini provider
and report measured token usage, latency, completeness, and score breakdowns.
"""
from pathlib import Path
from app.main import create_app
from app.pipeline.run import run_presentation_analysis
from app.prompts.registry import PromptRegistry
from app.providers.factory import build_provider
from config.settings import get_settings


def run_eval():
    settings = get_settings()
    print(f"=== Running Live Evaluation with Provider: {settings.provider} ===")
    print(f"Model: {settings.gemini_model} | Pacing: {settings.gemini_call_pacing_seconds}s | Batch Size: {settings.claim_batch_size}")

    provider = build_provider(settings)
    prompts = PromptRegistry(settings.prompts_dir)

    sample_files = [
        "sample.pptx",
        "objective_claims.pptx",
        "track_b_test.pptx",
        "correction_test.pptx",
    ]

    for fname in sample_files:
        path = Path(fname)
        if not path.exists():
            print(f"Skipping {fname} (not found)")
            continue

        content = path.read_bytes()
        print(f"\n--- Analyzing {fname} ({len(content)} bytes) ---")
        try:
            res = run_presentation_analysis(
                filename=fname,
                content=content,
                provider=provider,
                prompts=prompts,
                settings=settings,
            )
            print(f"Status: {res.status} | Schema Version: {res.schema_version}")
            print(f"Completeness: slides_total={res.completeness.slides_total}, processed={res.completeness.slides_processed}, failed={res.completeness.slides_failed}, claims_extracted={res.completeness.claims_extracted}")
            print(f"Scores: overall={res.scores.overall}, fact_accuracy={res.scores.fact_accuracy}, evidence_coverage={res.scores.evidence_coverage}, claim_reliability={res.scores.claim_reliability}")
            print(f"Summary: total={res.summary.total_claims}, supported={res.summary.supported}, contradicted={res.summary.contradicted}, project_unsupported={res.summary.project_unsupported}, plausibility_flag={res.summary.plausibility_flag}, unclear={res.summary.unclear}")
            print(f"Usage: total_calls={res.usage.total_calls}, tokens_in={res.usage.tokens_in}, tokens_out={res.usage.tokens_out}, total_tokens={res.usage.total_tokens}, duration_ms={res.usage.duration_ms:.1f}ms")
            print(f"Calls by stage: {res.usage.calls_by_stage}")
            print(f"Tokens by stage: {res.usage.tokens_by_stage}")
            print(f"Unified Claims count: {len(res.unified_claims)}")
            for uc in res.unified_claims:
                print(f"  [{uc.claim_id}] (Slide {uc.slide_number}) Track: {uc.track} | Status: {uc.status} | Conf: {uc.confidence:.2f} | Text: \"{uc.text}\"")
                if uc.correction:
                    print(f"    -> Correction: {uc.correction}")
                if uc.evidence:
                    print(f"    -> Evidence: {uc.evidence[0].source_url}")
        except Exception as exc:
            print(f"ERROR analyzing {fname}: {exc}")


if __name__ == "__main__":
    run_eval()

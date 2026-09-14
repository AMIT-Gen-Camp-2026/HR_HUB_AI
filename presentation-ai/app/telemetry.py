"""Structured logging for every model call.

Every LLM/embedding call goes through `record_call` so we always know: which
analysis it belonged to, which provider/model served it, how many tokens it used, and
whether it succeeded.

NEVER log raw presentation/slide text here — only counts and identifiers.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass

log = logging.getLogger("app.telemetry")

_session_records: list[CallRecord] = []


@dataclass
class CallRecord:
    run_id: str
    stage: str
    provider: str
    prompt_version: str
    model_version: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    retried: int = 0
    outcome: str = "ok"
    duration_ms: float = 0.0


def get_session_records() -> list[CallRecord]:
    return list(_session_records)


def reset_session_records() -> None:
    _session_records.clear()


@contextmanager
def record_call(stage: str, provider: str, model_version: str, prompt_version: str):
    """Usage:
        with record_call("claim_extraction", provider.name, "", prompt_version) as rec:
            completion = await provider.complete(...)
            rec.model_version = completion.model_version
            rec.tokens_in, rec.tokens_out = completion.tokens_in, completion.tokens_out
    The initial model_version should be the model selected for the request when it
    is known, so failed calls remain attributable in logs.
    """
    rec = CallRecord(
        run_id=str(uuid.uuid4()),
        stage=stage,
        provider=provider,
        model_version=model_version,
        prompt_version=prompt_version,
    )
    start = time.perf_counter()
    try:
        yield rec
    except Exception:
        rec.outcome = "error"
        raise
    finally:
        rec.duration_ms = (time.perf_counter() - start) * 1000.0
        _session_records.append(rec)
        log.info(
            "call stage=%s provider=%s model=%s prompt=%s tokens_in=%d tokens_out=%d "
            "retried=%d outcome=%s duration_ms=%.1f run_id=%s",
            rec.stage, rec.provider, rec.model_version, rec.prompt_version,
            rec.tokens_in, rec.tokens_out, rec.retried, rec.outcome, rec.duration_ms, rec.run_id,
        )

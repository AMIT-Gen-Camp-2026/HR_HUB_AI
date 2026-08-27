"""Model version, prompt version, latency, tokens, cost — on every call, no exceptions.

The AI operations report reads these records and nothing else, so a missing record
means a number nobody can defend.
"""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator

log = logging.getLogger("app.telemetry")


@dataclass
class CallRecord:
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    feature: str = ""
    provider: str = ""
    model_version: str = ""
    prompt_version: str = ""
    latency_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    retried: int = 0
    outcome: str = "ok"          # ok | invalid_schema | timeout | refused
    # NEVER put candidate data in here.

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@contextmanager
def record_call(feature: str, provider: str, model_version: str, prompt_version: str) -> Iterator[CallRecord]:
    rec = CallRecord(
        feature=feature,
        provider=provider,
        model_version=model_version,
        prompt_version=prompt_version,
    )
    started = time.perf_counter()
    try:
        yield rec
    except Exception:
        rec.outcome = "error"
        raise
    finally:
        rec.latency_ms = int((time.perf_counter() - started) * 1000)
        log.info("ai_call %s", rec.as_dict())
        # TODO(sprint-2): persist to the ai_request_log table instead of only logging.

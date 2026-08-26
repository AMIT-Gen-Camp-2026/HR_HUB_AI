"""One error envelope for every failure. No stack trace ever reaches a caller."""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

log = logging.getLogger("app.errors")


class AIServiceError(Exception):
    code = "ai_service_error"
    status = 500


class FeatureDisabled(AIServiceError):
    code = "feature_disabled"
    status = 200  # a documented state, not an error


class ProviderUnavailable(AIServiceError):
    code = "provider_unavailable"
    status = 503


class SchemaValidationFailed(AIServiceError):
    code = "schema_validation_failed"
    status = 422


class BudgetExceeded(AIServiceError):
    code = "budget_exceeded"
    status = 429


class RedactionFailed(AIServiceError):
    """Refuse the call rather than send an identifier outside the platform."""

    code = "redaction_failed"
    status = 500


def register_exception_handlers(app: "FastAPI") -> None:
    """FastAPI-only. fastapi is imported here (not at module level) so that
    the exception classes above stay importable under a Flask-only install
    (e.g. app/providers/stub_provider.py imports ProviderUnavailable from
    this module and is loaded by tests/conftest.py for every test run)."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.exception_handler(AIServiceError)
    async def _handle(request: Request, exc: AIServiceError) -> JSONResponse:
        correlation_id = str(uuid.uuid4())
        log.warning("%s | %s | %s", exc.code, correlation_id, exc)
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "correlation_id": correlation_id,
                }
            },
        )
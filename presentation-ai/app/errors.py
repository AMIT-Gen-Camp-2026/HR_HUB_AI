"""Centralized domain exceptions and Flask JSON error handlers.

Every public error code must match the project's fixed error-code contract.
Routes and services should raise AppError subclasses instead of returning
ad-hoc error dictionaries.

All API error messages are English-only.
"""

from __future__ import annotations

from flask import Flask, jsonify
from werkzeug.exceptions import RequestEntityTooLarge


class AppError(Exception):
    """Base exception for expected application errors."""

    code: str = "INTERNAL_ERROR"
    status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidFile(AppError):
    code = "INVALID_FILE"
    status = 400


class UnsupportedFormat(AppError):
    code = "UNSUPPORTED_FORMAT"
    status = 400


class FileTooLarge(AppError):
    code = "FILE_TOO_LARGE"
    status = 413


class CorruptedFile(AppError):
    code = "CORRUPTED_FILE"
    status = 400


class ExtractionFailed(AppError):
    code = "EXTRACTION_FAILED"
    status = 422


class ClaimExtractionFailed(AppError):
    code = "CLAIM_EXTRACTION_FAILED"
    status = 502


class SchemaValidationFailed(AppError):
    """Raised when model output remains invalid after the allowed repair attempt."""

    code = "CLAIM_EXTRACTION_FAILED"
    status = 502


class FactCheckFailed(AppError):
    code = "FACT_CHECK_FAILED"
    status = 502


class ScoringFailed(AppError):
    code = "SCORING_FAILED"
    status = 500


class InternalError(AppError):
    code = "INTERNAL_ERROR"
    status = 500

class DailyQuotaExceeded(AppError):
    code = "DAILY_QUOTA_EXCEEDED"
    status = 429


def _error_response(code: str, message: str, status: int):
    """Build the standard API error response."""

    return (
        jsonify(
            {
                "status": "error",
                "error": {
                    "code": code,
                    "message": message,
                },
            }
        ),
        status,
    )


def register_error_handlers(app: Flask) -> None:
    """Register centralized JSON error handlers for the Flask application."""

    @app.errorhandler(AppError)
    def _handle_app_error(err: AppError):
        return _error_response(
            code=err.code,
            message=err.message,
            status=err.status,
        )

    @app.errorhandler(RequestEntityTooLarge)
    def _handle_request_too_large(err: RequestEntityTooLarge):
        return _error_response(
            code="FILE_TOO_LARGE",
            message="Uploaded file exceeds the size limit.",
            status=413,
        )

    @app.errorhandler(404)
    def _handle_not_found(err):
        return _error_response(
            code="NOT_FOUND",
            message="Route not found.",
            status=404,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(err: Exception):
        app.logger.exception("Unhandled exception")

        return _error_response(
            code="INTERNAL_ERROR",
            message="An unexpected internal error occurred.",
            status=500,
        )
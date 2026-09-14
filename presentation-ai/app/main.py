"""Flask application factory. Builds the provider and prompt registry ONCE at
startup and stores them on app.extensions — pipeline code never builds its own
provider instance.
"""
from __future__ import annotations

import logging

from flask import Flask

from app.api.routes_health import health_bp
from app.api.routes_presentation import presentation_bp
from app.errors import register_error_handlers
from app.prompts.registry import PromptRegistry
from app.providers.factory import build_provider
from config.settings import get_settings

MAX_CONTENT_LENGTH = 25 * 1024 * 1024  # 25MB cap (docs/DECISIONS.md section 13 security note)


def create_app() -> Flask:
    settings = get_settings()

    logging.basicConfig(level=settings.log_level)
    logger = logging.getLogger(__name__)

    provider = build_provider(settings)
    prompts = PromptRegistry(settings.prompts_dir)

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

    app.extensions["settings"] = settings
    app.extensions["provider"] = provider
    app.extensions["prompts"] = prompts

    app.register_blueprint(health_bp)
    app.register_blueprint(presentation_bp)
    register_error_handlers(app)

    logger.info(
        "Presentation AI startup complete | provider=%s | gemini_model=%s | gemini_grounding_model=%s | embedding_model=%s",
        settings.provider, settings.gemini_model, settings.gemini_grounding_model, settings.embedding_model,
    )

    return app

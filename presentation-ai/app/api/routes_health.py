"""GET /healthz — trivial liveness check, no dependencies on provider/pipeline."""
from __future__ import annotations

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/healthz")
def healthz():
    return jsonify({"status": "ok"})
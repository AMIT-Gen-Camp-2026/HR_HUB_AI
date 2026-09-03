"""
app/main.py

نقطة الدخول الرئيسية للـ Flask API.
بيربط الـ pipeline اللي شغال بالفعل (extraction -> prompt -> model -> json)
خلف endpoints بسيطة.
"""

import json
import logging
import os

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from pydantic import ValidationError as PydanticValidationError

from config.settings import config
from app.pipeline.ranking import rank as compute_ranking
from app.pipeline.run import (
    clean_and_query,
    extract_raw_text,
    extraction_status,
    get_extraction_metadata,
)
from app.providers.hf_provider import ModelInferenceError
from app.schemas.cv import CVSchema, JobDescription
from app.security.auth import require_api_key
from app.security.file_validator import (
    FileValidationError,
    generate_safe_storage_name,
    validate_extension,
    validate_file_content,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

# rate limiting عام على مستوى الـ app + حد أخص على endpoint الاستخراج
limiter = Limiter(get_remote_address, app=app, default_limits=["30 per hour"])


@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/v1/cv/evaluate", methods=["POST"])
@require_api_key
@limiter.limit("10 per hour")
def evaluate_cv():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No 'file' field in form-data."}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    job_description_raw = request.form.get("job_description")
    if job_description_raw is None:
        return jsonify({"success": False, "error": "Missing 'job_description' field in form-data."}), 400

    try:
        job_description_payload = json.loads(job_description_raw)
    except json.JSONDecodeError:
        return jsonify({"success": False, "error": "job_description must be valid JSON."}), 400

    if not isinstance(job_description_payload, dict):
        return jsonify({"success": False, "error": "job_description must be a JSON object."}), 400

    try:
        job_description = JobDescription(**job_description_payload)
    except PydanticValidationError as e:
        return jsonify({"success": False, "error": e.errors()}), 422

    try:
        ext = validate_extension(file.filename, config.ALLOWED_EXTENSIONS)
    except FileValidationError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    temp_name = generate_safe_storage_name(file.filename)
    temp_path = os.path.join(config.UPLOAD_FOLDER, temp_name)

    try:
        file.save(temp_path)

        try:
            validate_file_content(temp_path, ext)
        except FileValidationError as e:
            return jsonify({"success": False, "error": str(e)}), 400

        raw_text = extract_raw_text(temp_path, ext)
        if not raw_text or not raw_text.strip():
            return jsonify({"success": False, "error": "No extractable text found in file."}), 422

        try:
            validated_cv = clean_and_query(raw_text)
        except ModelInferenceError as e:
            logger.error("Model inference/validation failed across full chain: %s", e)
            return jsonify(
                {
                    "success": False,
                    "error": "Model inference failed. Please try again.",
                    "extraction_status": "FAILED",
                }
            ), 502

        status = extraction_status(validated_cv)

        if status == "EMPTY":
            return jsonify(
                {
                    "success": True,
                    "cv": validated_cv.model_dump(),
                    "ranking": None,
                    "extraction_status": "EMPTY",
                    "extraction_metadata": get_extraction_metadata(),
                }
            ), 200

        if not config.RANKING_ENABLED:
            return jsonify(
                {
                    "success": True,
                    "cv": validated_cv.model_dump(),
                    "ranking": None,
                    "extraction_status": status,
                    "extraction_metadata": get_extraction_metadata(),
                }
            ), 200

        try:
            ranking_result = compute_ranking(validated_cv, job_description)
        except Exception:
            logger.exception("Unexpected error during ranking")
            return jsonify({"success": False, "error": "Internal server error."}), 500

        return jsonify(
            {
                "success": True,
                "cv": validated_cv.model_dump(),
                "ranking": ranking_result.model_dump(),
                "extraction_status": status,
                "extraction_metadata": get_extraction_metadata(),
            }
        ), 200

    except Exception:
        logger.exception("Unexpected error during CV evaluation")
        return jsonify({"success": False, "error": "Internal server error."}), 500

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    config.validate()
    app.run(debug=config.FLASK_DEBUG, port=config.FLASK_PORT)
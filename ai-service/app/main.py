"""
app/main.py

نقطة الدخول الرئيسية للـ Flask API.
بيربط الـ pipeline اللي شغال بالفعل (extraction -> prompt -> model -> json)
خلف endpoints بسيطة.
"""

import logging
import os
import re
import tempfile

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from pydantic import ValidationError as PydanticValidationError

from config.settings import config
from app.pipeline.ranking import rank as compute_ranking
from app.pipeline.run import extract_raw_text, clean_and_query
from app.pipeline.video_transcription import (
    ASRModelUnavailable,
    ASRInferenceError,
    VideoDecodeError,
    transcribe_video,
)
from app.providers.hf_provider import ModelInferenceError
from app.schemas.cv import CVSchema, JobDescription
from app.security.file_validator import (
    FileValidationError,
    generate_safe_storage_name,
    validate_extension,
    validate_file_content,
    validate_video_content,
    validate_video_mime_type,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = max(config.MAX_CONTENT_LENGTH, config.VIDEO_MAX_SIZE_BYTES)

os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

# rate limiting عام على مستوى الـ app + حد أخص على endpoint الاستخراج
limiter = Limiter(get_remote_address, app=app, default_limits=["30 per hour"])


def _safe_video_error(error: Exception, status_code: int, message: str):
    """Return detail only for local development, never revealing paths or credentials."""
    body = {"success": False, "error": message}
    detail = getattr(error, "detail", None)
    if config.FLASK_DEBUG and detail:
        body["detail"] = re.sub(r"[A-Za-z]:\\[^\s]+|/[^\s]+", "[path]", detail)
    return jsonify(body), status_code


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"success": False, "error": "Uploaded file exceeds the server size limit."}), 413


@app.errorhandler(429)
def request_rate_limited(_error):
    return jsonify({"success": False, "error": "Request rate limit exceeded. Please try again later."}), 429


@app.route("/api/v1/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/api/v1/cv/extract", methods=["POST"])
@limiter.limit("10 per hour")
def extract_cv():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No 'file' field in form-data."}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    try:
        ext = validate_extension(file.filename, config.ALLOWED_EXTENSIONS)
    except FileValidationError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    temp_name = generate_safe_storage_name(file.filename)
    temp_path = os.path.join(config.UPLOAD_FOLDER, temp_name)

    try:
        file.save(temp_path)

        if os.path.getsize(temp_path) > config.MAX_CONTENT_LENGTH:
            return jsonify({"success": False, "error": "CV file exceeds the 10 MB limit."}), 413

        # تحقق من المحتوى الحقيقي للملف (magic bytes)، مش بس امتداده
        try:
            validate_file_content(temp_path, ext)
        except FileValidationError as e:
            return jsonify({"success": False, "error": str(e)}), 400

        raw_text = extract_raw_text(temp_path, ext)
        if not raw_text or not raw_text.strip():
            return jsonify({"success": False, "error": "No extractable text found in file."}), 422

        # clean_and_query دلوقتي بيتحقق من كل محاولة (parse_and_validate جوه
        # app/pipeline/run.py). لو موديل رجّع JSON تالف أو مش مطابق للـ schema،
        # هيتحسب فشل وهننتقل للموديل اللي بعده في MODEL_CHAIN تلقائيًا.
        try:
            validated_cv = clean_and_query(raw_text)
        except ModelInferenceError as e:
            logger.error("Model inference/validation failed across full chain: %s", e)
            return jsonify(
                {"success": False, "error": "Model inference failed. Please try again."}
            ), 502

        return jsonify({"success": True, "cv": validated_cv.model_dump()}), 200

    except Exception as e:
        logger.exception("Unexpected error during extraction")
        return jsonify({"success": False, "error": "Internal server error."}), 500

    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route("/api/v1/rank", methods=["POST"])
@limiter.limit("60 per hour")
def rank_candidate():
    """
    بتاخد {"candidate": <CVSchema JSON>, "job_description": <JobDescription JSON>}
    وترجّع RankingResult. الـ candidate عادة هو ناتج /api/v1/cv/extract زي
    ما هو (validated_cv.model_dump()) - مفيش استخراج إضافي هنا، الـ scoring
    كله deterministic (algorithm، مش LLM call) في app/pipeline/ranking.py.
    """
    if not config.RANKING_ENABLED:
        return jsonify({"success": False, "error": "Ranking is switched off."}), 200

    payload = request.get_json(silent=True)
    if payload is None or not isinstance(payload, dict):
        return jsonify({"success": False, "error": "Request body must be a JSON object."}), 400

    try:
        candidate = CVSchema(**payload.get("candidate", {}))
        job_description = JobDescription(**payload.get("job_description", {}))
    except PydanticValidationError as e:
        return jsonify({"success": False, "error": e.errors()}), 422

    try:
        result = compute_ranking(candidate, job_description)
    except Exception:
        logger.exception("Unexpected error during ranking")
        return jsonify({"success": False, "error": "Internal server error."}), 500

    return jsonify({"success": True, "result": result.model_dump()}), 200


@app.route("/api/v1/video/transcribe", methods=["POST"])
@limiter.limit("10 per hour")
def transcribe_uploaded_video():
    """Transcribe an uploaded MP4/MOV/MKV/WebM without retaining the video."""
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No 'file' field in form-data."}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "No video selected."}), 400

    temp_path: str | None = None
    try:
        try:
            extension = validate_extension(file.filename, config.VIDEO_ALLOWED_EXTENSIONS)
            validate_video_mime_type(file.mimetype)
        except FileValidationError as error:
            return jsonify({"success": False, "error": str(error)}), 415

        with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as temporary_file:
            temp_path = temporary_file.name
            file.save(temporary_file)

        size = os.path.getsize(temp_path)
        if size == 0:
            return jsonify({"success": False, "error": "The uploaded video is empty."}), 422
        if size > config.VIDEO_MAX_SIZE_BYTES:
            return jsonify({"success": False, "error": "Video exceeds the configured size limit."}), 413
        try:
            validate_video_content(temp_path, extension)
        except FileValidationError as error:
            return jsonify({"success": False, "error": str(error)}), 415

        result = transcribe_video(temp_path)
        return jsonify({"success": True, **result}), 200
    except ASRModelUnavailable as error:
        logger.error("Video transcription unavailable at ASR setup: %s", error, exc_info=True)
        return _safe_video_error(error, 503, str(error))
    except VideoDecodeError as error:
        return jsonify({"success": False, "error": str(error)}), 422
    except ASRInferenceError as error:
        logger.error("Video transcription failed at ASR inference: %s", error, exc_info=True)
        return _safe_video_error(error, 500, str(error))
    except Exception:
        logger.exception("Unexpected error during video transcription")
        return jsonify({"success": False, "error": "Video transcription could not be completed."}), 500
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


if __name__ == "__main__":
    config.validate()
    app.run(debug=config.FLASK_DEBUG, port=config.FLASK_PORT)

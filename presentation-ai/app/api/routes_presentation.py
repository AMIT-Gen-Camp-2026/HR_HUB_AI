"""POST /api/v1/presentation/analyze — HTTP layer only:
validates the upload, delegates everything else to app/pipeline/run.py.
"""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from app.errors import CorruptedFile, InvalidFile, UnsupportedFormat
from app.pipeline.run import run_presentation_analysis

presentation_bp = Blueprint("presentation", __name__, url_prefix="/api/v1/presentation")

# Standard file header magic bytes
_ZIP_MAGIC_BYTES = b"PK\x03\x04"
_PDF_MAGIC_BYTES = b"%PDF-"


@presentation_bp.post("/analyze")
def analyze():
    if "file" not in request.files or not request.files["file"].filename:
        raise InvalidFile("No file was provided under the 'file' field.")

    uploaded = request.files["file"]
    safe_filename = secure_filename(uploaded.filename) or "presentation.pptx"
    filename_lower = uploaded.filename.lower()

    if not (filename_lower.endswith(".pptx") or filename_lower.endswith(".pdf")):
        raise UnsupportedFormat("Only .pptx and .pdf files are supported.")

    content = uploaded.read()
    if not content:
        raise InvalidFile("The uploaded file is empty.")

    # Validate file magic signatures
    if filename_lower.endswith(".pptx") and not content.startswith(_ZIP_MAGIC_BYTES):
        raise CorruptedFile("The uploaded file is not a valid PowerPoint archive.")
    if filename_lower.endswith(".pdf") and not content.startswith(_PDF_MAGIC_BYTES):
        raise CorruptedFile("The uploaded file is not a valid PDF document.")

    result = run_presentation_analysis(
        filename=safe_filename,
        content=content,
        provider=current_app.extensions["provider"],
        prompts=current_app.extensions["prompts"],
        settings=current_app.extensions["settings"],
        applicant_id=request.form.get("applicant_id"),
        job_id=request.form.get("job_id"),
    )
    return jsonify(result.model_dump()), 200
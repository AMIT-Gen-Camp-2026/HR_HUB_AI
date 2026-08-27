"""HTTP contract tests for the isolated Flask video transcription endpoint."""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import main
from app.pipeline.video_transcription import ASRInferenceError, ASRModelUnavailable, VideoDecodeError


def _mp4_bytes(extra: bytes = b"") -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomiso2" + extra


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main.config, "VIDEO_MAX_SIZE_BYTES", 1024 * 1024)
    return main.app.test_client()


def _video_data(name: str = "demo.mp4", content: bytes | None = None) -> dict:
    return {"file": (io.BytesIO(content if content is not None else _mp4_bytes()), name, "video/mp4")}


def test_valid_video_returns_structured_transcript_and_cleans_up(client, monkeypatch: pytest.MonkeyPatch) -> None:
    saved_path: Path | None = None

    def fake_transcribe(path: str) -> dict:
        nonlocal saved_path
        saved_path = Path(path)
        assert saved_path.exists()
        return {
            "language": "ar",
            "language_probability": 0.99,
            "text": "مرحبا hello",
            "segments": [{"start": 0.0, "end": 1.2, "text": "مرحبا hello"}],
        }

    monkeypatch.setattr(main, "transcribe_video", fake_transcribe)
    response = client.post("/api/v1/video/transcribe", data=_video_data(), content_type="multipart/form-data")

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "language": "ar",
        "language_probability": 0.99,
        "text": "مرحبا hello",
        "segments": [{"start": 0.0, "end": 1.2, "text": "مرحبا hello"}],
    }
    assert saved_path is not None and not saved_path.exists()


def test_missing_video_file_is_rejected(client) -> None:
    response = client.post("/api/v1/video/transcribe", data={}, content_type="multipart/form-data")
    assert response.status_code == 400


def test_unsupported_extension_is_rejected(client) -> None:
    response = client.post("/api/v1/video/transcribe", data=_video_data("demo.avi"), content_type="multipart/form-data")
    assert response.status_code == 415


def test_oversized_video_is_rejected(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main.config, "VIDEO_MAX_SIZE_BYTES", 16)
    response = client.post("/api/v1/video/transcribe", data=_video_data(content=_mp4_bytes(b"too large")), content_type="multipart/form-data")
    assert response.status_code == 413


def test_model_loading_failure_is_safe(client, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(_path: str) -> dict:
        raise ASRModelUnavailable("The transcription model could not be loaded.")

    monkeypatch.setattr(main, "transcribe_video", unavailable)
    response = client.post("/api/v1/video/transcribe", data=_video_data(), content_type="multipart/form-data")
    assert response.status_code == 503
    assert "model" in response.get_json()["error"].lower()


def test_decode_failure_is_reported_as_validation_error(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "transcribe_video", lambda _path: (_ for _ in ()).throw(VideoDecodeError("No spoken audio was detected in this video.")))
    response = client.post("/api/v1/video/transcribe", data=_video_data(), content_type="multipart/form-data")
    assert response.status_code == 422


def test_asr_inference_failure_is_reported_without_traceback(client, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "transcribe_video", lambda _path: (_ for _ in ()).throw(ASRInferenceError("ASR inference failed.")))
    response = client.post("/api/v1/video/transcribe", data=_video_data(), content_type="multipart/form-data")
    assert response.status_code == 500
    assert response.get_json()["error"] == "ASR inference failed."

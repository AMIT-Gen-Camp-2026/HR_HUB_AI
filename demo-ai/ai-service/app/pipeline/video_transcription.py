"""Lazy multilingual video transcription using faster-whisper and PyAV decoding."""

from __future__ import annotations

from functools import lru_cache
import logging
from pathlib import Path
from typing import Any

from config.settings import config

logger = logging.getLogger(__name__)


class VideoTranscriptionError(Exception):
    """Base class for safe, user-facing video transcription failures."""


class ASRModelUnavailable(VideoTranscriptionError):
    """Raised when the optional ASR runtime or configured model cannot load."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


class VideoDecodeError(VideoTranscriptionError):
    """Raised when a validated file cannot be decoded as a video with audio."""


class ASRInferenceError(VideoTranscriptionError):
    """Raised when the loaded ASR model cannot transcribe decoded audio."""

    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.detail = detail


def _diagnostic_detail(error: Exception) -> str:
    """Keep development diagnostics useful without echoing paths or credentials."""
    message = str(error).replace("\n", " ").strip()
    if any(marker in message.lower() for marker in ("token", "api_key", "authorization")):
        message = "sensitive error text withheld"
    return f"{type(error).__name__}: {message[:300]}"


def _resolve_runtime() -> tuple[str, str]:
    """Choose CUDA when it is available; otherwise use quantized CPU inference."""
    requested_device = config.VIDEO_ASR_DEVICE.lower()
    requested_compute_type = config.VIDEO_ASR_COMPUTE_TYPE.lower()
    if requested_device not in {"auto", "cpu", "cuda"}:
        raise ASRModelUnavailable("VIDEO_ASR_DEVICE must be auto, cpu, or cuda.")
    if requested_device == "auto":
        try:
            import ctranslate2

            device = "cuda" if ctranslate2.get_cuda_device_count() > 0 else "cpu"
        except Exception:
            device = "cpu"
    else:
        device = requested_device
    compute_type = requested_compute_type
    if compute_type == "auto":
        compute_type = "float16" if device == "cuda" else "int8"
    return device, compute_type


@lru_cache(maxsize=1)
def get_asr_model() -> Any:
    """Load the configured multilingual model only for the first video request."""
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        logger.exception("Video ASR failed at runtime import: %s", _diagnostic_detail(error))
        raise ASRModelUnavailable(
            "The multilingual ASR runtime is not installed on this server.",
            _diagnostic_detail(error),
        ) from error
    device, compute_type = _resolve_runtime()
    try:
        return WhisperModel(config.VIDEO_ASR_MODEL, device=device, compute_type=compute_type)
    except Exception as error:
        logger.exception("Video ASR failed at model load: %s", _diagnostic_detail(error))
        raise ASRModelUnavailable("The configured transcription model could not be loaded.", _diagnostic_detail(error)) from error


def extract_audio(video_path: str | Path) -> Any:
    """Decode and resample the untrusted video audio through faster-whisper's PyAV backend."""
    try:
        from faster_whisper import decode_audio

        audio = decode_audio(str(video_path))
    except ImportError as error:
        logger.exception("Video ASR failed at audio decoder import: %s", _diagnostic_detail(error))
        raise ASRModelUnavailable("The multilingual ASR runtime is not installed on this server.", _diagnostic_detail(error)) from error
    except Exception as error:
        logger.exception("Video transcription failed at audio extraction: %s", _diagnostic_detail(error))
        raise VideoDecodeError("The video audio could not be extracted. Ensure it contains a supported audio track.") from error
    if len(audio) == 0:
        raise VideoDecodeError("No audio stream was found in this video.")
    return audio


def transcribe_video(video_path: str | Path) -> dict[str, Any]:
    """Decode a temporary video and transcribe it without translating its language.

    faster-whisper uses PyAV to decode/resample the audio stream. PyAV bundles the
    FFmpeg libraries, so the server does not need a separate FFmpeg executable.
    """
    audio = extract_audio(video_path)
    try:
        segments, info = get_asr_model().transcribe(
            audio, task="transcribe", language=None, beam_size=5, vad_filter=True
        )
        result_segments = [
            {"start": round(segment.start, 2), "end": round(segment.end, 2), "text": segment.text.strip()}
            for segment in segments
            if segment.text.strip()
        ]
    except ASRModelUnavailable:
        raise
    except Exception as error:
        logger.exception("Video transcription failed at ASR inference: %s", _diagnostic_detail(error))
        raise ASRInferenceError("ASR inference failed.", _diagnostic_detail(error)) from error
    text = " ".join(segment["text"] for segment in result_segments).strip()
    if not text:
        raise VideoDecodeError("No spoken audio was detected in this video.")
    return {
        "language": getattr(info, "language", "unknown"),
        "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        "text": text,
        "segments": result_segments,
    }

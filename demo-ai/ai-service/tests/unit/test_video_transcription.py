"""Unit tests for multilingual ASR result shaping; no model weights are downloaded."""
from __future__ import annotations

from types import SimpleNamespace

from app.pipeline import video_transcription


def test_transcription_preserves_mixed_language_segments(monkeypatch) -> None:
    class FakeModel:
        def transcribe(self, *_args, **kwargs):
            assert kwargs["task"] == "transcribe"
            assert kwargs["language"] is None
            return (
                iter([
                    SimpleNamespace(start=0.0, end=1.5, text=" مرحبا "),
                    SimpleNamespace(start=1.5, end=3.0, text=" hello world "),
                ]),
                SimpleNamespace(language="ar", language_probability=0.94),
            )

    monkeypatch.setattr(video_transcription, "get_asr_model", lambda: FakeModel())
    monkeypatch.setattr(video_transcription, "extract_audio", lambda _path: "decoded-audio")
    result = video_transcription.transcribe_video("temporary-video.mp4")

    assert result["language"] == "ar"
    assert result["text"] == "مرحبا hello world"
    assert result["segments"][1]["text"] == "hello world"

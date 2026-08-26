"""Written test-first. This must fail against an unprotected path before redact.py exists."""
from __future__ import annotations

import pytest

from app.pipeline.redact import assert_clean, redact

SAMPLE = """
Ahmed Hassan
National ID: 29803081402633
Email: ahmed.hassan@example.com
Mobile: 01012345678
"""


def test_identifiers_are_removed() -> None:
    cleaned, count = redact(SAMPLE)
    assert count >= 3
    assert "29803081402633" not in cleaned
    assert "ahmed.hassan@example.com" not in cleaned
    assert "01012345678" not in cleaned


def test_outbound_payload_is_clean() -> None:
    cleaned, _ = redact(SAMPLE)
    assert_clean(cleaned)


def test_unprotected_payload_is_caught() -> None:
    with pytest.raises(AssertionError):
        assert_clean(SAMPLE)

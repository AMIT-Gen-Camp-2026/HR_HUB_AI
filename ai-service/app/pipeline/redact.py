"""Remove direct identifiers before anything leaves the platform.

Written test-first: tests/unit/test_redaction.py must fail against the unprotected path
before this module exists. A redaction failure REFUSES the call — it never sends the payload.
"""
from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"(?:\+?20|0)?1[0125]\d{8}\b")          # Egyptian mobile
NATIONAL_ID = re.compile(r"\b[23]\d{13}\b")                 # 14 digits, starts 2 or 3
ANY_LONG_DIGITS = re.compile(r"\b\d{10,}\b")


def redact(text: str) -> tuple[str, int]:
    """Returns (redacted_text, count_removed)."""
    count = 0
    for pattern, token in (
        (NATIONAL_ID, "[NATIONAL_ID]"),
        (EMAIL, "[EMAIL]"),
        (PHONE, "[PHONE]"),
        (ANY_LONG_DIGITS, "[NUMBER]"),
    ):
        text, n = pattern.subn(token, text)
        count += n
    return text, count


def assert_clean(payload: str) -> None:
    """Used by the test that inspects the outbound body. Raises if anything slipped through."""
    for pattern in (NATIONAL_ID, EMAIL, PHONE):
        if pattern.search(payload):
            raise AssertionError(f"Identifier found in outbound payload: {pattern.pattern}")


def extract_contact_info(text: str) -> dict[str, str | None]:
    """Regex-extract email/phone straight from the CV text, before redact() runs.

    These two fields are deterministic string patterns - there is no reason to send
    them to a third-party model provider just to have the model echo them back into
    personal_info.email / personal_info.phone. This lets the pipeline redact() the
    text before it leaves the platform while still populating those two fields
    reliably (run.py overwrites the model's own personal_info.email/phone with
    these values - regex on the raw text is more trustworthy than an LLM re-reading
    a string it was explicitly never shown).

    Only returns the first match of each - a CV normally lists one primary email
    and one primary phone number.
    """
    email_match = EMAIL.search(text)
    phone_match = PHONE.search(text)
    return {
        "email": email_match.group(0) if email_match else None,
        "phone": phone_match.group(0) if phone_match else None,
    }
"""Unit tests for PDF extraction module (app/pipeline/extract_pdf.py)."""
from __future__ import annotations

import pymupdf
import pytest

from app.pipeline.extract_pdf import (
    PdfEncryptedError,
    PdfPackageCorrupted,
    extract_pdf,
)
from app.pipeline.extract_pptx import ExtractedPresentation


def create_sample_pdf_bytes(pages_text: list[str]) -> bytes:
    """Helper to create synthetic in-memory PDF bytes using PyMuPDF."""
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        page.insert_text((50, 50), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_extract_pdf_valid():
    pages = ["Slide 1 Title\nSome content for slide 1.", "Slide 2 Title\nSome content for slide 2."]
    pdf_bytes = create_sample_pdf_bytes(pages)

    extracted = extract_pdf(pdf_bytes)

    assert isinstance(extracted, ExtractedPresentation)
    assert extracted.slide_count == 2
    assert len(extracted.slides) == 2
    assert extracted.slides[0].slide_number == 1
    assert extracted.slides[1].slide_number == 2
    assert len(extracted.failed_slide_numbers) == 0


def test_extract_pdf_corrupt_bytes():
    bad_bytes = b"%PDF-1.4 corrupt content that is not a real pdf"
    with pytest.raises(PdfPackageCorrupted):
        extract_pdf(bad_bytes)


def test_extract_pdf_encrypted(tmp_path):
    # Create an encrypted PDF
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), "Secret content")

    perm = int(
        pymupdf.PDF_PERM_ACCESSIBILITY
        | pymupdf.PDF_PERM_PRINT
        | pymupdf.PDF_PERM_COPY
        | pymupdf.PDF_PERM_ANNOTATE
    )
    encrypt_meth = pymupdf.PDF_ENCRYPT_AES_128
    pdf_bytes = doc.tobytes(
        encryption=encrypt_meth,
        owner_pw="owner123",
        user_pw="secret123",
        permissions=perm,
    )
    doc.close()

    with pytest.raises(PdfEncryptedError):
        extract_pdf(pdf_bytes)

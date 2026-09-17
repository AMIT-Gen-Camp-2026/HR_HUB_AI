"""PDF bytes -> structured per-slide content. DETERMINISTIC — no AI, no provider call.
Every returned element MUST keep its slide_number (1-indexed PDF page number): this is
what lets the final report point HR to the exact slide/page with an issue.
"""
from __future__ import annotations

import logging

import pymupdf

from app.pipeline.extract_pptx import ExtractedPresentation, SlideContent, SlideElement

logger = logging.getLogger(__name__)


class PdfPackageCorrupted(Exception):
    """Raised when the PDF bytes can't be parsed because the file is corrupt or invalid."""


class PdfEncryptedError(Exception):
    """Raised when the PDF is password-protected and cannot be decrypted without a password."""


def extract_pdf(file_bytes: bytes) -> ExtractedPresentation:
    try:
        doc = pymupdf.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise PdfPackageCorrupted(f"Invalid or corrupted PDF document: {exc}") from exc

    try:
        if doc.is_encrypted:
            if not doc.authenticate(""):
                raise PdfEncryptedError("The PDF file is password-protected.")

        slides: list[SlideContent] = []
        failed_slides: list[int] = []

        for idx, page in enumerate(doc, start=1):
            title = None
            elements: list[SlideElement] = []
            slide_err = None

            try:
                # 1. Extract tables if present using PyMuPDF table detection
                try:
                    tables = page.find_tables()
                    if tables and tables.tables:
                        for table in tables:
                            extracted_table = table.extract()
                            if extracted_table:
                                rows = [
                                    [str(cell or "").strip() for cell in row]
                                    for row in extracted_table
                                ]
                                rendered = "\n".join(" | ".join(r) for r in rows)
                                if rendered.strip():
                                    elements.append(SlideElement(type="table", content=rendered))
                except Exception as e:
                    logger.debug("Failed to extract tables on PDF page %d: %s", idx, e)

                # 2. Extract text blocks
                try:
                    blocks = page.get_text("blocks")
                    for b in blocks:
                        # block structure: (x0, y0, x1, y1, text, block_no, block_type)
                        # block_type == 0 indicates text
                        if len(b) >= 5 and b[4]:
                            text = b[4].strip()
                            if not text:
                                continue
                            # Heuristic for page/slide title: first short line/block
                            if title is None and len(text.splitlines()) == 1 and len(text) < 120:
                                title = text
                                continue
                            elements.append(SlideElement(type="text", content=text))
                except Exception as e:
                    logger.debug("Failed to extract text blocks on PDF page %d: %s", idx, e)

                if not elements and not title:
                    slide_err = "slide_contains_no_extractable_text"
                    if idx not in failed_slides:
                        failed_slides.append(idx)

            except Exception as exc:
                logger.warning("Error extracting elements from PDF page %d: %s", idx, exc, exc_info=True)
                slide_err = str(exc)
                if idx not in failed_slides:
                    failed_slides.append(idx)

            slides.append(
                SlideContent(
                    slide_number=idx,
                    title=title,
                    elements=elements,
                    extraction_error=slide_err,
                )
            )

        return ExtractedPresentation(
            slide_count=len(slides),
            slides=slides,
            failed_slide_numbers=failed_slides,
        )

    finally:
        doc.close()

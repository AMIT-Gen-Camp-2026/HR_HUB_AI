"""normalize.py is deterministic — these tests need no provider, no fixtures beyond
plain Python objects."""
from app.pipeline.extract_pptx import ExtractedPresentation, SlideContent, SlideElement
from app.pipeline.normalize import normalize


def test_removes_duplicate_elements_within_a_slide():
    slide = SlideContent(slide_number=1, title=None, elements=[
        SlideElement(type="text", content="Our model achieved 95% accuracy."),
        SlideElement(type="text", content="Our model achieved 95% accuracy."),
    ])
    result = normalize(ExtractedPresentation(slide_count=1, slides=[slide]))
    assert len(result.slides[0].elements) == 1


def test_drops_empty_elements():
    slide = SlideContent(slide_number=1, title=None, elements=[SlideElement(type="text", content="   ")])
    result = normalize(ExtractedPresentation(slide_count=1, slides=[slide]))
    assert result.slides[0].elements == []


# TODO: add a case with mixed Arabic/English content once we have a real sample —
# assert numbers/units are never stripped (original spec §9).

from app.pipeline.extract_pptx import ExtractedPresentation, SlideContent, SlideElement
from app.pipeline.normalize import normalize

slide = SlideContent(slide_number=1, title=None, elements=[
    SlideElement(type='text', content='Our model achieved 95% accuracy.'),
    SlideElement(type='text', content='Our model achieved 95% accuracy.'),
    SlideElement(type='text', content='   '),
    SlideElement(type='text', content='النموذج حقق دقة 95%'),
])
result = normalize(ExtractedPresentation(slide_count=1, slides=[slide]))
for el in result.slides[0].elements:
    print(repr(el.content))

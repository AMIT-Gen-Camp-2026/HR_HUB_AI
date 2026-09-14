from pptx import Presentation

prs = Presentation()

s1 = prs.slides.add_slide(prs.slide_layouts[1])
s1.shapes.title.text = 'Technology Stack'
s1.placeholders[1].text_frame.text = 'Prolog is a low-level programming language.'

s2 = prs.slides.add_slide(prs.slide_layouts[1])
s2.shapes.title.text = 'Backend'
s2.placeholders[1].text_frame.text = 'We used PostgreSQL as our primary database.'

prs.save('correction_test.pptx')
print('created')

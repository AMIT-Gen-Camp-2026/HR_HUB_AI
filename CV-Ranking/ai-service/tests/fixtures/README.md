# Test fixtures

**Synthetic CVs only.** Never commit a real candidate's CV, not even one with the name
changed — the rest of the document still identifies a real person.

Generate fixtures with `scripts/make_fixture_cv.py`, or write them by hand.

Required coverage:

- [ ] English, single column, PDF
- [ ] English, two column, PDF
- [ ] Arabic, PDF
- [ ] Mixed Arabic / English, PDF
- [ ] DOCX
- [ ] Scanned / image-only PDF (must be detected and flagged, not silently empty)
- [ ] A CV whose projects mention libraries absent from its Skills section

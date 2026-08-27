# cv-extraction @ v1

| | |
|---|---|
| Purpose | Field-level accuracy of CV parsing, and skill recall / precision |
| Size | TARGET 100 CVs — currently 0 |
| Labelled by | *(name)* |
| Labelled on | *(date)* |
| Split | fixed in `labels.jsonl` — `split` field: train / val / test |
| Languages | English, Arabic, mixed — in proportion to the real data |

## Label format — one JSON object per line in `labels.jsonl`

```json
{
  "id": "cv-001",
  "file": "synthetic/cv-001.pdf",
  "language": "en",
  "split": "test",
  "personal": {"full_name": "…", "email": "…", "phone": null, "national_id": null},
  "education": [{"degree": "…", "institution": "…", "year": 2018}],
  "experience": [{"title": "…", "company": "…", "start": "2019-01", "end": "2022-06"}],
  "skills_explicit": ["Python", "SQL"],
  "skills_inferred": ["Pandas", "Scikit-learn", "XGBoost"],
  "skills_must_not_appear": ["TensorFlow", "Deep Learning", "Machine Learning"]
}
```

`skills_must_not_appear` is the field that measures **invention**. Fill it with the
plausible-but-absent skills a model might hallucinate from this CV's project descriptions.
It is the most valuable column in this file.

## Inter-labeller agreement

Two people label the same 10 CVs independently and the disagreement is recorded here.
Disagreement between two humans is the ceiling on any metric — a model cannot be measured
more precisely than the labels allow.

# Evaluation

No AI feature is accepted without a number. This folder is how the number is produced.

## Rules

1. Datasets are **committed to the repository**, versioned, with a README naming who
   labelled them and when.
2. The train / validation / test split is **fixed in the dataset**, not decided by the
   runner at run time.
3. Every feature is compared against a **documented naive baseline**. A model that does not
   beat its baseline is not shipped.
4. Metrics are reported on the **held-out test set only**, with the definition written next
   to the number.
5. Every reported number is reproducible from a committed script and a tracked MLflow run.

## Running

```bash
make eval
python -m eval.runners.run_extraction --dataset cv-extraction@v1
python -m eval.runners.run_extraction --dataset cv-extraction@v1 --subset ci --fail-under 0.60
```

## Metrics we report

| Feature | Metric | Target |
|---|---|---|
| CV extraction | Field-level accuracy, **per field, never averaged into one number** | ≥ 85% |
| Skills — explicit | Recall | ≥ 95% |
| Skills — inferred | Recall | ≥ 70% |
| Skills — inferred | **Precision** | **≥ 90%** |
| Skills | Invented skills (not present in the document) | ≈ 0 |
| Ranking | Agreement with human shortlist | ≥ 70% |
| Duplicate detection | Recall / false-positive rate, **reported together** | ≥ 90% / < 15% |

> Precision on inferred skills matters more than recall. Missing a skill costs a reviewer
> thirty seconds. Inventing one puts a false claim on a candidate's record.

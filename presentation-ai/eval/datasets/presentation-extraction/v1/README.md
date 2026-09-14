# Dataset v1 — Ground Truth Presentation Claims

This dataset provides a hand-annotated, independent ground truth benchmark for evaluating:
1. **Claim Extraction**: Precision, Recall, and F1.
2. **Classification**: `track` (`objective` | `project_specific`) and `claim_type` accuracy.
3. **Verification**: Accuracy broken down separately for Track A (Grounded fact-checking) and Track B (Plausibility assessment).
4. **Plausibility Error Analysis**: False Positive Rate and False Negative Rate on plausibility flags.

## Dataset Composition (12 Presentations, 38 Claims)

| ID | File | Slides | Language | Topics / Modalities |
|---|---|---|---|---|
| 01 | `01_en_ml_results.pptx` | 3 | English | CNN accuracy, dataset size, microservices, ResNet-50 |
| 02 | `02_en_objective_tech.pptx` | 2 | English | PostgreSQL JSON (true), FastAPI Starlette (true), Prolog low-level (false) |
| 03 | `03_ar_performance.pptx` | 2 | Arabic | 94% accuracy, 10k images dataset, PostgreSQL DB |
| 04 | `04_mixed_lang.pptx` | 2 | Mixed Ar/En | 88% F1-score, SVM algorithm, Redis pub/sub (true) |
| 05 | `05_implausible.pptx` | 2 | English | 99.9% accuracy (flagged), 100% precision (flagged), 200 images |
| 06 | `06_metrics_table.pptx` | 2 | English | Tabular evaluation metrics: 91% acc, 87% recall, 45ms latency |
| 07 | `07_filler_only.pptx` | 3 | English | Title, Agenda, Thank you slides (zero checkable claims) |
| 08 | `08_arch_algo_biz.pptx` | 2 | English | Hexagonal arch, XGBoost, 2s invoice processing, 30% cost reduction |
| 09 | `09_dataset_details.pptx` | 2 | English | 50k images, 10 classes, Kaggle public data sources |
| 10 | `10_latency_r2.pptx` | 2 | English | R2=0.42 (borderline), 120ms latency, Python lists vs NumPy (false) |
| 11 | `11_speaker_notes_details.pptx` | 3 | English | Speaker notes: LLaMA fine-tune (15k dialogues), RTX 4090 GPU (35 tok/s), MongoDB multi-doc ACID (false) |
| 12 | `12_borderline_rag_ar_en.pptx` | 4 | Mixed Ar/En | LangChain/FAISS 25k docs, Table (Recall@5=78%, MRR=0.65), Elasticsearch BM25 (true), 99.8% satisfaction (flagged) |

## Label Schema (`labels.jsonl`)

Each line is a JSON object with:
```json
{
  "filename": "string",
  "claims": [
    {
      "text": "string (verbatim gold text)",
      "slide_number": 1,
      "track": "objective | project_specific",
      "claim_type": "performance | dataset | architecture | technology | algorithm | capability | business",
      "expected_status": "supported | contradicted | project_unsupported | plausibility_flag | unclear",
      "is_factual_truth": true | false | null,
      "flag_reason": "string explanation if flagged, else null"
    }
  ]
}
```

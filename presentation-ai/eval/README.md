# Evaluation

Measures claim-extraction and fact-check quality against a manually labeled dataset
(original spec §44-45). Run this before shipping any prompt-version bump — see
docs/PROMPTS.md.

```bash
python eval/runners/run_extraction.py --dataset eval/datasets/presentation-extraction/v1
```

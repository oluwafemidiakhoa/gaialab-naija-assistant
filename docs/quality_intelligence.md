# Quality intelligence

`src/quality_intelligence.py` provides deterministic, CPU-only advisory checks for
clarity, completeness, duplication, credential safety, high-risk escalation,
Nigerian context, Nigerian Pidgin, and business-writing structure. Every
deduction includes its check, severity, score deduction, and explanation.

Automated output never constitutes factual validation or human approval.
Banking, healthcare, government services, education, agriculture, and travel are
always marked `factual_review_required`.

Run:

```bash
python scripts/quality_score_dataset.py --version v0.6
python scripts/quality_score_dataset.py --version v0.6 --record-id v06-banking-001
```

Runs are write-once. When the requested output already contains a run, a new UTC
timestamped directory is created. The optional LLM provider is disabled by
default and cannot make a network call without an explicitly supplied evaluator.

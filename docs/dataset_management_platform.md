# GaiaLab dataset management platform

The dataset platform is a free, local-first workflow for immutable version
snapshots, append-only human review, deterministic hashes, duplicate discovery,
release publishing, and cross-model benchmark summaries.

It does not turn the current corpus into a culturally validated production
dataset. GaiaLab Naija v0.6 remains a synthetic draft pending independent review
by Nigerian speakers, small-business owners, and relevant domain professionals.

## Storage model

```text
data/registry/
  registry_events.jsonl
  versions/<version>/records.jsonl
  reviews/<version>.jsonl

data/releases/<version>/
  <version>.jsonl
  <version>.csv
  dataset_statistics.json
  semantic_duplicates.json
  dataset_manifest.json
```

An imported version is a write-once snapshot. Importing the same version twice
fails instead of replacing it. Releases are also write-once.

Reviews are appended to a per-version event log. Approving, rejecting, or editing
does not rewrite the snapshot or an earlier event. Once a record is approved, its
content and review decision are immutable. Editing approved content creates a new
draft revision with `supersedes_sha256` pointing to the approved example.

Every registered record includes:

- dataset version and revision;
- review status, reviewer, review date, quality score, and notes;
- creation time and source/license provenance;
- a SHA-256 hash over canonical example content; and
- the previous hash when a revision supersedes another example.

Quality scores use a human-selected 0–5 scale. The platform never generates a
quality score automatically.

## Register and publish a version

Use Python 3.11 from the repository root:

```bash
python scripts/dataset_platform.py import \
  --version v0.6 \
  --input data/v0.6/generated/v0.6_all.jsonl

python scripts/dataset_platform.py list
python scripts/dataset_platform.py duplicates --threshold 0.82
python scripts/dataset_platform.py publish --version v0.6
```

Do not register a legacy version until every record has specific, documented
`source` and `license` values. The existing v0.4 and v0.5 chat JSONL files omit
those fields, so the platform deliberately rejects them rather than inventing
provenance.

Publishing computes statistics and a semantic-duplicate report across every
registered version and preserved revision. Duplicate detection is deterministic
and offline: it compares unigram and bigram token-frequency vectors using cosine
similarity. This is a review heuristic, not proof that two examples have
identical meaning. Review all flagged pairs manually.

## Human review interface

Install the repository dependencies and run:

```bash
streamlit run app/dataset_review.py
```

Set `GAIALAB_DATASET_REGISTRY` only when using a non-default registry directory.
The interface supports filtering, editing, approving, and rejecting examples.
The reviewer field is required. Review events include an ISO-8601 UTC date and
the selected quality score.

Use stable reviewer IDs rather than private contact details. Do not put personal
data, credentials, sensitive prompts, or confidential customer material into the
dataset or review notes.

## Benchmark reports

Benchmark generation and reporting are separate. Model runs write response files;
human reviewers then enter scores using the existing reviewer guide. To compare
all supplied model versions:

```bash
python scripts/benchmark_report_all_versions.py \
  --report-id gaia-review-2026-07
```

Reports are created under `evaluation/reports/<report-id>/`. Reusing an existing
report ID fails, preserving every comparison. With no positional inputs, every
JSONL file directly under `evaluation/results/` is included. Only numeric scores
already entered by humans are averaged; absent scores remain absent. Reports stay
labelled as drafts pending independent human review.

## Contributor verification

Before publishing a dataset version:

```bash
python -m src.validate_dataset data/gaialab_naija_v0.1.jsonl \
  --output-dir /tmp/gaialab-v01-validation
python scripts/validate_v06_dataset.py
python -m pytest
```

Also confirm:

1. every source and license is specific and compatible;
2. no approved snapshot or release path was replaced;
3. semantic-duplicate flags were reviewed by humans;
4. high-risk content has relevant professional review;
5. evaluation prompts remain separate from training data; and
6. no model weights, secrets, sensitive prompts, or generated checkpoints are
   staged.

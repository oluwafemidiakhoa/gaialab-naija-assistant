# Governed LoRA training pipeline

This pipeline trains an adapter only from an immutable release candidate whose
split hashes and per-record eligibility decisions pass validation. Training is
explicit, GPU-only, and local to the environment where the command is run. It
does not commit, push, tag, publish a dataset, or upload a model unless the
operator separately supplies `--push-to-hub`.

Candidate identity is exact and immutable:

- release label `v0.7.0-rc.1` maps only to
  `data/release_candidates/v0.7-rc1/`; its manifest records zero eligible
  examples and three empty splits;
- release label `v0.7.0-rc.3` maps only to
  `data/release_candidates/v0.7-rc3/`; its manifest records seven eligible
  examples split into five train, one validation, and one held-out benchmark.

The seven approvals were recorded after `rc1` and belong to `rc3`. They are
not copied or relabelled as `rc1`. The historical
`configs/training/v0.7.0-rc.1.yaml` remains available to reproduce the safe
empty-dataset refusal. Runnable examples use
`configs/training/v0.7.0-rc.3.yaml`.

The existing `data/release_candidates/v0.8-rc1/` directory is retained as
immutable incident evidence, but it is **invalid for governed training**. It
was built after the legacy release builder recursively discovered human-event
shaped records in a quarantined pytest-pollution backup rather than reading
only the authoritative ledger. It must not be deleted, overwritten, relabelled,
trained from, or represented as `v0.8.0-rc.1`. Its internally consistent split
hashes do not establish valid human authorization. Recovery must use a new
candidate version after legitimate decisions exist in
`evaluation/review_audit/v0.8-draft/human_events.jsonl`.

Both candidates were built from source release `v0.6`. The release builder's
audit root is `evaluation/review_audit`, with v0.6 human decisions in
`evaluation/review_audit/v0.6/human_events.jsonl`. Candidate manifests and
split files remain under `data/release_candidates/<candidate>/`.

Seven examples are sufficient to exercise the pipeline, not to support
meaningful fine-tuning or production quality claims. A larger,
representative, independently reviewed dataset and human evaluation are still
required. Generate any future candidate as a new immutable directory; do not
edit or replace an existing candidate.

## Governance gates

Before any model is loaded, the trainer:

1. requires non-empty training and validation JSONL files;
2. validates the three-message `system`, `user`, `assistant` schema;
3. recomputes every example SHA-256;
4. rejects duplicate IDs and normalized prompts;
5. rejects ID, record-hash, and prompt leakage between splits;
6. verifies split counts and file hashes against the candidate manifest;
7. matches every row to an eligible decision with the same record SHA-256; and
8. refuses a non-empty output directory unless resume or explicit overwrite is
   requested.

Release construction reads only the authoritative
`evaluation/review_audit/<version>/human_events.jsonl` ledger. Files under an
`incidents/` directory, backups, generated reports, and other JSON files are
never active review authority. New v0.8 candidate manifests must bind the
authoritative ledger with `human_audit_sha256` and
`human_audit_event_count`; training fails closed when either field is absent.
This prevents quarantined audit evidence from being replayed into eligibility.

Immutable candidate rows may still say `draft`: approval is append-only and is
represented by the eligibility report derived from human audit events. The
trainer never changes those source rows. For standalone test data without a
candidate manifest, each row must carry explicit approval plus completed
technical review, and regulated categories must carry domain-review evidence.

`--overwrite-output-dir` does not delete an earlier run. It moves the existing
directory to a timestamped sibling backup before creating a new directory.
Resume keeps the existing directory and passes the checkpoint explicitly to
Transformers.

## Local validation

Use Python 3.11. A dry run validates data, governance evidence, hashes,
configuration, output safety, Git identity, and CUDA metadata. It does not
download or load a model.

```bash
python scripts/train_governed_lora.py \
  --config configs/training/v0.7.0-rc.3.yaml \
  --output-dir outputs/dry-runs/v0.7.0-rc.3 \
  --dry-run
```

This validates the seven-record `v0.7-rc3` candidate without loading a model.
Running the same command with the `rc.1` configuration is expected to stop
with an empty-dataset refusal.

CPU is permitted only for `--dry-run` and validation-only `--smoke-test`.
Normal training exits before importing the ML training stack when CUDA is not
available. A smoke test on a GPU performs at most five optimizer steps; a CPU
smoke test validates only and records that limitation in its manifest.

## Kaggle GPU setup

1. Create a Kaggle notebook with a GPU accelerator and internet access.
2. Add `HF_TOKEN` through Kaggle Secrets if private model access or an optional
   upload is needed. Never place it in a cell, file, command argument, or log.
3. Attach the immutable `v0.7-rc3` candidate directory as a private, read-only
   Kaggle Dataset. Release candidates are intentionally Git-ignored and are
   not present in a fresh clone.
4. Set `GAIALAB_CANDIDATE_DIR` to the exact Kaggle-mounted directory containing
   `release_candidate_manifest.json`, `eligibility_report.json`, and the three
   split files.
5. Clone the repository and check out the reviewed branch, commit, or tag.
6. Install `requirements-training.txt`.
7. Run the full tests and the governed dry run.
8. Run a five-step GPU smoke test in a fresh output directory.
9. Inspect both manifests before starting a full run.

The executable notebook is
[`notebooks/gaialab_governed_lora_kaggle.ipynb`](../notebooks/gaialab_governed_lora_kaggle.ipynb).

Full training, once a non-empty candidate is approved:

```bash
export GAIALAB_CANDIDATE_DIR=/kaggle/input/<private-dataset>/<candidate-directory>
python scripts/train_governed_lora.py \
  --config configs/training/v0.7.0-rc.3.yaml \
  --train-file "$GAIALAB_CANDIDATE_DIR/training.jsonl" \
  --validation-file "$GAIALAB_CANDIDATE_DIR/validation.jsonl" \
  --output-dir /kaggle/working/gaialab-v0.7.0-rc.3-lora
```

Replace the two bracketed path components with the path Kaggle actually
mounts; the repository does not guess or fabricate it. The notebook reads the
same `GAIALAB_CANDIDATE_DIR` value and stops if the directory is absent.

Resume after interruption:

```bash
python scripts/train_governed_lora.py \
  --config configs/training/v0.7.0-rc.3.yaml \
  --train-file "$GAIALAB_CANDIDATE_DIR/training.jsonl" \
  --validation-file "$GAIALAB_CANDIDATE_DIR/validation.jsonl" \
  --output-dir /kaggle/working/gaialab-v0.7.0-rc.3-lora \
  --resume-from-checkpoint /kaggle/working/gaialab-v0.7.0-rc.3-lora/checkpoint-25
```

The base model defaults to `Qwen/Qwen2.5-0.5B-Instruct`. Override it only after
licence, chat-template, and architecture review. The pipeline uses the
tokenizer chat template and masks system/user tokens so loss is computed on the
assistant response. LoRA targets Qwen attention projections and uses no
quantization or `bitsandbytes`.

The default rank 16, alpha 32, and warmup ratio 0.05 reuse the repository's
existing Qwen LoRA configuration rather than introducing an unsupported tuning
claim. They are conservative operational defaults, not evidence of optimal
quality; the manifest records any overrides.

## Run manifest and artefacts

Every completed dry run, smoke validation, smoke training, full training, or
started training that fails after Trainer creation gets a write-once
`training_manifest.json`. It contains:

- prerelease and base-model identity, including resolved revision when known;
- Git commit and branch;
- exact input paths, SHA-256 values, and row counts;
- resolved arguments, LoRA settings, and seed;
- dependency, CUDA, and GPU information;
- completion status, metrics, and checkpoint paths; and
- candidate manifest and eligibility-report hashes.

The adapter is saved under `adapter/`; Trainer checkpoints remain under
`checkpoint-*`. Tokens and credentials are never included. Training outputs,
weights, optimizer state, predictions, cache files, and notebook temporary
files are ignored by Git.

```text
<output-dir>/
  adapter/                       # PEFT adapter and tokenizer
  checkpoint-*/                  # resumable Trainer state
  training_manifest.json         # first attempt, write-once
  training_manifest.resume-*.json
  training_metrics.json
  training_metrics.resume-*.json
<evaluation-output>/
  predictions.jsonl
  evaluation_summary.json
```

## Evaluation

Evaluation accepts only a file named `validation.jsonl` or
`held_out_benchmark.jsonl`, requires the associated training split, and repeats
the governance, file-hash, and leakage checks.

```bash
python scripts/evaluate_governed_adapter.py \
  --base-model Qwen/Qwen2.5-0.5B-Instruct \
  --release-version v0.7.0-rc.3 \
  --adapter-dir /kaggle/working/gaialab-v0.7.0-rc.3-lora/adapter \
  --training-file "$GAIALAB_CANDIDATE_DIR/training.jsonl" \
  --evaluation-file "$GAIALAB_CANDIDATE_DIR/held_out_benchmark.jsonl" \
  --output-dir /kaggle/working/gaialab-v0.7.0-rc.3-evaluation
```

It writes deterministic-greedy predictions with record IDs, prompts, expected
responses, and generated responses, plus loss, perplexity, hashes, and a
summary. A set below 30 examples is explicitly labelled too small for reliable
release claims. These automatic metrics do not replace Nigerian human
evaluation, and expected answers remain reference material rather than
automatically assigned quality scores.

## Optional Hugging Face upload

Upload is off by default. The planned repository is:

```text
oluwafemidiakhoa/gaialab-naija-assistant-v0.7.0-rc.3-lora
```

After training and evaluation have succeeded and a human has approved release:

```bash
python scripts/train_governed_lora.py \
  --config configs/training/v0.7.0-rc.3.yaml \
  --train-file "$GAIALAB_CANDIDATE_DIR/training.jsonl" \
  --validation-file "$GAIALAB_CANDIDATE_DIR/validation.jsonl" \
  --output-dir /kaggle/working/gaialab-v0.7.0-rc.3-lora \
  --push-to-hub \
  --hub-model-id oluwafemidiakhoa/gaialab-naija-assistant-v0.7.0-rc.3-lora
```

This is a separate explicit operation. A successful training run alone does
not authorize publishing. Check the model card, source and base-model licences,
evaluation evidence, and release governance before upload.

## Verification checklist

```bash
python -m src.validate_dataset data/releases/v0.6/v0.6.jsonl \
  --output-dir /tmp/gaialab-v0.6-validation
python -m pytest -q
python scripts/train_governed_lora.py \
  --config configs/training/v0.7.0-rc.3.yaml --dry-run
git status --short
```

Confirm that no token, model weight, checkpoint, generated prediction, or
sensitive prompt is staged. Do not claim that this prerelease was trained or
evaluated unless the corresponding manifest and reproducible artefacts exist.

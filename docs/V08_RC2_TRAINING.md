# Governed v0.8 RC2 Colab training

This workflow trains only from the immutable `v0.8-rc2` release candidate. It is an experimental pipeline-validation run, not evidence that the adapter is production-ready or culturally validated. The earlier `v0.8-rc1` candidate remains immutable and must not be used for governed training because its eligibility evidence included non-authoritative quarantined test-pollution events.

## Bound candidate evidence

The checked-in configuration is `configs/training/v0.8.0-rc.2.yaml`. It binds the training process to:

- source version: `v0.8-draft`
- candidate version: `v0.8-rc2`
- release label: `v0.8.0-rc.2`
- eligible/excluded records: 80 / 40
- training/validation/held-out records: 68 / 6 / 6
- authoritative audit: `evaluation/review_audit/v0.8-draft/human_events.jsonl`
- authoritative audit event count: 248
- authoritative audit SHA-256: `1c953505356ae8241f588f5b23f5f3ba4487e369584f789ffe26dde9b0bc8b5f`
- source manifest: `data/releases/v0.8-draft/dataset_manifest.json`
- source manifest SHA-256: `67bd340d2f0400222517b0b86f7f41d91839d23b11f22477e4d24b02983ffd00`
- release-candidate SHA-256: `755165026934afc68ade34fd50610016af284cbe2cd769f3b019892e15f3189d`
- training SHA-256: `92e256eb82a64be41f7d5da6df7dafc360020f7360b386751c8540fdfb927732`
- validation SHA-256: `4bdf6777660c61e3e33aad2f83896bacc8d51e567a3fcc47935af39f68d444ec`
- held-out SHA-256: `2ecd247a9c8865b76346748f927b21939a81e9c4cc2607d6622570221cdc2748`

The trainer fails before model loading if any identity, hash, audit count, split count, eligibility proof, or split-isolation check differs. The held-out benchmark is never passed to the trainer as training or validation data.

The raw authoritative ledger is intentionally excluded from the Colab package because it is repository-ignored governance evidence and may contain private reviewer identifiers. Colab verifies the expected audit SHA-256 and event count recorded inside the canonically hashed candidate manifest; it does not accept a copied ledger as new authority.

## Local preflight

Use Python 3.11. Local commands validate governance only; do not train on a CPU.

```powershell
.\.venv311\Scripts\python.exe -m pytest -q
.\.venv311\Scripts\python.exe scripts\train_governed_lora.py `
  --config configs\training\v0.8.0-rc.2.yaml `
  --output-dir ..\gaialab-output\v0.8.0-rc.2-dry-run `
  --dry-run
```

Output directories are append-only: choose a new path if the target already exists. The dry-run verifies the candidate without importing or downloading the model.

## Colab procedure

Open `notebooks/gaialab_governed_lora_colab_v08_rc2.ipynb` in a fresh CUDA-enabled Colab runtime and run the notebook from the first cell. The notebook:

1. clones the exact branch or commit and installs `requirements-colab.txt` without replacing Colab's CUDA PyTorch;
2. accepts the immutable candidate ZIP through browser upload—Google Drive is not used;
3. validates the audit, source manifest, candidate, split hashes, counts, and pairwise split isolation before loading Qwen;
4. runs repository tests and a governed dry-run;
5. runs a five-step smoke test only when CUDA is available;
6. leaves full training and Hugging Face upload disabled by default.

Review the smoke manifest and metrics before changing `RUN_FULL_TRAINING` to `True`. Upload requires a separate explicit `PUSH_TO_HUB=True`. Store `HF_TOKEN` only in Colab Secrets and enable notebook access; the notebook never prints the token. The destination is private by default:

`mgbam/gaialab-naija-assistant-v0.8.0-rc.2-lora`

Possessing a token is not upload consent. The v0.7 and v0.8-rc1 output paths and adapters are never used as RC2 destinations.

## Resume and evaluation

In Colab, set `RESUME_CHECKPOINT` to an existing RC2 checkpoint below the external `OUTPUT_ROOT`, then enable `RUN_FULL_TRAINING`. The equivalent command is:

```bash
python scripts/train_governed_lora.py \
  --config configs/training/v0.8.0-rc.2.yaml \
  --train-file "$CANDIDATE_DIR/training.jsonl" \
  --validation-file "$CANDIDATE_DIR/validation.jsonl" \
  --held-out-benchmark-file "$CANDIDATE_DIR/held_out_benchmark.jsonl" \
  --source-manifest-file "$SOURCE_MANIFEST" \
  --output-dir "$RC2_OUTPUT/full" \
  --resume-from-checkpoint "$RC2_OUTPUT/full/checkpoint-N"
```

Evaluate validation and held-out data in separate output directories:

```bash
python scripts/evaluate_governed_adapter.py \
  --release-version v0.8.0-rc.2 \
  --base-model Qwen/Qwen2.5-0.5B-Instruct \
  --adapter-dir "$RC2_OUTPUT/full/adapter" \
  --training-file "$CANDIDATE_DIR/training.jsonl" \
  --evaluation-file "$CANDIDATE_DIR/validation.jsonl" \
  --output-dir "$RC2_OUTPUT/evaluations/validation"

python scripts/evaluate_governed_adapter.py \
  --release-version v0.8.0-rc.2 \
  --base-model Qwen/Qwen2.5-0.5B-Instruct \
  --adapter-dir "$RC2_OUTPUT/full/adapter" \
  --training-file "$CANDIDATE_DIR/training.jsonl" \
  --evaluation-file "$CANDIDATE_DIR/held_out_benchmark.jsonl" \
  --output-dir "$RC2_OUTPUT/evaluations/held_out_benchmark"
```

The evaluator rejects overlap with the training split. Its metrics describe reproducible loss and generation output only; they are not a substitute for independent Nigerian human evaluation.

## Output contract

All generated artifacts stay outside the repository (the notebook defaults to `/content/gaialab-output`). A completed run produces append-only versions of:

- `training_manifest.json`
- `environment_report.json`
- `training_metrics.json`
- `validation_metrics.json`
- `held_out_metrics.json`
- separate validation and held-out `predictions.<split>.jsonl` files
- `reproducibility_report.json`

Do not commit checkpoints, adapters, logs, tokens, predictions containing sensitive prompts, or other generated model artifacts.

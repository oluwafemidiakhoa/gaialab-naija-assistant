# GaiaLab v0.4 Dataset Starter Pack

This pack creates a reviewed, deduplicated, reproducible v0.4 training dataset from four JSONL source files.

## Files

- `data/raw/customer_service.jsonl`
- `data/raw/safety_scams.jsonl`
- `data/raw/professional_boundaries.jsonl`
- `data/raw/nigerian_english.jsonl`
- `scripts/build_v04_dataset.py`
- `run_prepare_v04_dataset.bat`

## Install into your repository

Copy every file and folder from this pack into:

`C:\Users\adminidiakhoa\gaialab-naija-assistant`

Allow Windows to merge the existing `data` and `scripts` folders. Do not replace unrelated files.

## Build the dataset

From the project root, run:

```cmd
run_prepare_v04_dataset.bat
```

Or run directly:

```cmd
.venv\Scripts\python.exe scripts\build_v04_dataset.py --input-dir data\raw --output-dir data\v0.4 --validation-ratio 0.10 --seed 42
```

## Outputs

The command creates:

- `data\v0.4\v0.4_training.jsonl`
- `data\v0.4\v0.4_validation.jsonl`
- `data\v0.4\v0.4_all_reviewed.jsonl`
- `data\v0.4\dataset_manifest.json`

## Important

The included examples are a high-quality starter set, not the final 325-example dataset. Add reviewed examples to the four files in `data\raw`, one JSON object per line. Run the batch file again after every update.

Do not copy private customer data, passwords, account numbers, OTPs, medical records, or personal identifiers into the dataset.

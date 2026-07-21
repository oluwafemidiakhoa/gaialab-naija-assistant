"""Convert validated GaiaLab records into chat-formatted Hugging Face datasets."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from src.validate_dataset import read_jsonl, validate_records

if TYPE_CHECKING:
    from datasets import DatasetDict

SYSTEM_PROMPT = (
    "You are GaiaLab Naija Assistant, an experimental assistant for Nigerian "
    "small-business owners. Be clear, respectful, practical, and do not invent facts."
)


def format_example(example: dict[str, str]) -> dict[str, object]:
    user_text = example["instruction"]
    if example["input"].strip():
        user_text += f"\n\nContext:\n{example['input'].strip()}"
    return {
        **example,
        "prompt": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "completion": [{"role": "assistant", "content": example["output"]}],
    }


def load_validated_splits(
    train_path: Path, validation_path: Path
) -> dict[str, list[dict[str, str]]]:
    """Load both splits and reject invalid rows or cross-split leakage."""
    train, _ = validate_records(read_jsonl(train_path))
    validation, _ = validate_records(read_jsonl(validation_path))
    train_fingerprints = {
        json.dumps(record, ensure_ascii=False, sort_keys=True) for record in train
    }
    validation_fingerprints = {
        json.dumps(record, ensure_ascii=False, sort_keys=True) for record in validation
    }
    if train_fingerprints & validation_fingerprints:
        raise ValueError("Exact duplicate records appear in both dataset splits.")
    return {"train": train, "validation": validation}


def prepare_dataset(train_path: Path, validation_path: Path) -> "DatasetDict":
    from datasets import Dataset, DatasetDict

    raw = load_validated_splits(train_path, validation_path)
    return DatasetDict(
        {
            split: Dataset.from_list([format_example(row) for row in records])
            for split, records in raw.items()
        }
    )


def remove_generated_output(path: Path) -> None:
    """Remove an explicitly selected generated directory, rejecting broad paths."""
    resolved = path.resolve()
    working_directory = Path.cwd().resolve()
    home_directory = Path.home().resolve()
    protected = {
        working_directory,
        *working_directory.parents,
        home_directory,
        *home_directory.parents,
        Path(resolved.anchor),
    }
    if resolved in protected:
        raise ValueError(f"Refusing to overwrite protected directory: {resolved}")
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=Path("prepared_data/train.jsonl"))
    parser.add_argument(
        "--validation", type=Path, default=Path("prepared_data/validation.jsonl")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("prepared_data/hf"))
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing generated output directory.",
    )
    args = parser.parse_args()
    try:
        if args.output_dir.exists():
            if not args.overwrite:
                raise ValueError(
                    f"Output directory already exists: {args.output_dir}. "
                    "Pass --overwrite to replace generated data."
                )
            remove_generated_output(args.output_dir)
        prepare_dataset(args.train, args.validation).save_to_disk(args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Dataset preparation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Prepared dataset saved to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

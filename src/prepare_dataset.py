"""Convert validated GaiaLab records into chat-formatted Hugging Face datasets."""

from __future__ import annotations

import argparse
from pathlib import Path

from datasets import Dataset, DatasetDict, load_dataset

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
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": example["output"]},
        ],
    }


def prepare_dataset(train_path: Path, validation_path: Path) -> DatasetDict:
    raw = load_dataset(
        "json",
        data_files={"train": str(train_path), "validation": str(validation_path)},
    )
    return DatasetDict(
        {
            split: Dataset.from_list([format_example(row) for row in dataset])
            for split, dataset in raw.items()
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", type=Path, default=Path("prepared_data/train.jsonl"))
    parser.add_argument(
        "--validation", type=Path, default=Path("prepared_data/validation.jsonl")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("prepared_data/hf"))
    args = parser.parse_args()
    prepare_dataset(args.train, args.validation).save_to_disk(args.output_dir)
    print(f"Prepared dataset saved to {args.output_dir}")


if __name__ == "__main__":
    main()

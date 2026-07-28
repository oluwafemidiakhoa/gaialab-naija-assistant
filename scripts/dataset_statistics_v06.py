"""Generate deterministic descriptive statistics for GaiaLab Naija v0.6."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from build_v06_dataset import DEFAULT_GENERATED_DIR, _display_path, atomic_write_text
from split_v06_dataset import load_jsonl


def _counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(record[field] for record in records).items()))


def generate_statistics(generated_dir: Path) -> dict[str, object]:
    all_records = load_jsonl(generated_dir / "v0.6_all.jsonl")
    training = load_jsonl(generated_dir / "v0.6_training.jsonl")
    validation = load_jsonl(generated_dir / "v0.6_validation.jsonl")
    statistics: dict[str, object] = {
        "dataset_version": "v0.6",
        "dataset_status": "draft_pending_independent_nigerian_human_review",
        "total_records": len(all_records),
        "training_records": len(training),
        "validation_records": len(validation),
        "category_counts": _counts(all_records, "category"),
        "risk_level_counts": _counts(all_records, "risk_level"),
        "split_category_counts": {
            "training": _counts(training, "category"),
            "validation": _counts(validation, "category"),
        },
        "split_risk_level_counts": {
            "training": _counts(training, "risk_level"),
            "validation": _counts(validation, "risk_level"),
        },
        "character_counts": {
            "user": sum(len(record["messages"][1]["content"]) for record in all_records),
            "assistant": sum(
                len(record["messages"][2]["content"]) for record in all_records
            ),
        },
    }
    output = generated_dir / "dataset_statistics.json"
    atomic_write_text(
        output,
        json.dumps(statistics, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        backup=False,
    )
    return statistics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-dir", type=Path, default=DEFAULT_GENERATED_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        statistics = generate_statistics(args.generated_dir)
    except (ValueError, OSError) as exc:
        print(f"v0.6 statistics failed: {exc}")
        return 1
    print(
        f"Wrote statistics for {statistics['total_records']} records to "
        f"{_display_path(args.generated_dir / 'dataset_statistics.json')}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

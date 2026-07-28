"""Validate GaiaLab Naija v0.6 CSV sources and write a machine-readable report."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from build_v06_dataset import (
    DEFAULT_GENERATED_DIR,
    DEFAULT_SOURCE_DIR,
    DatasetV06Error,
    _display_path,
    atomic_write_text,
    load_all_csvs,
    row_to_record,
    validate_rows,
)
from split_v06_dataset import load_jsonl


def _validate_generated_outputs(
    rows: list[dict[str, str]], generated_dir: Path
) -> dict[str, object]:
    expected = [row_to_record(row) for row in rows]
    combined = load_jsonl(generated_dir / "v0.6_all.jsonl")
    training = load_jsonl(generated_dir / "v0.6_training.jsonl")
    validation = load_jsonl(generated_dir / "v0.6_validation.jsonl")
    if combined != expected:
        raise DatasetV06Error(
            "v0.6_all.jsonl does not exactly match the validated CSV sources."
        )
    all_ids = {record["id"] for record in combined}
    training_ids = {record["id"] for record in training}
    validation_ids = {record["id"] for record in validation}
    if training_ids & validation_ids:
        raise DatasetV06Error("Training and validation splits overlap.")
    if training_ids | validation_ids != all_ids:
        raise DatasetV06Error(
            "Training and validation splits do not partition v0.6_all.jsonl."
        )
    if len(all_ids) != len(combined):
        raise DatasetV06Error("Generated combined JSONL contains duplicate IDs.")
    return {
        "combined_records": len(combined),
        "training_records": len(training),
        "validation_records": len(validation),
        "split_overlap": 0,
        "split_covers_combined": True,
    }


def validate_dataset(
    source_dir: Path,
    report_path: Path,
    generated_dir: Path | None = None,
) -> dict[str, object]:
    try:
        rows = validate_rows(load_all_csvs(source_dir))
        generated_checks = (
            _validate_generated_outputs(rows, generated_dir)
            if generated_dir is not None
            else None
        )
    except (DatasetV06Error, OSError) as exc:
        report: dict[str, object] = {
            "dataset_version": "v0.6",
            "status": "failed",
            "errors": str(exc).splitlines(),
        }
        atomic_write_text(
            report_path,
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            backup=False,
        )
        raise

    report = {
        "dataset_version": "v0.6",
        "status": "passed",
        "record_count": len(rows),
        "source_file_count": len({row["_source_file"] for row in rows}),
        "category_counts": dict(sorted(Counter(row["category"] for row in rows).items())),
        "risk_level_counts": dict(
            sorted(Counter(row["risk_level"] for row in rows).items())
        ),
        "checks": {
            "required_columns": "passed",
            "allowed_risk_levels": "passed",
            "non_empty_user_and_assistant": "passed",
            "id_prefix_v06": "passed",
            "source_synthetic": "passed",
            "status_draft": "passed",
            "duplicate_ids": 0,
            "duplicate_normalized_prompts": 0,
        },
        "generated_outputs": generated_checks,
        "limitations": [
            "Draft examples pending independent review by Nigerian speakers and domain professionals.",
            "This validation checks structure and duplication; it does not establish cultural or domain correctness.",
        ],
    }
    atomic_write_text(
        report_path,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        backup=False,
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_GENERATED_DIR / "validation_report.json",
    )
    parser.add_argument(
        "--generated-dir",
        type=Path,
        default=DEFAULT_GENERATED_DIR,
        help="Generated outputs to compare with the CSV sources.",
    )
    parser.add_argument(
        "--source-only",
        action="store_true",
        help="Validate only source CSVs without requiring generated outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = validate_dataset(
            args.source_dir,
            args.report,
            None if args.source_only else args.generated_dir,
        )
    except (DatasetV06Error, OSError) as exc:
        print(f"v0.6 validation failed: {exc}")
        return 1
    print(
        f"Validated {report['record_count']} records; report: "
        f"{_display_path(args.report)}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

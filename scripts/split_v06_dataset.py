"""Create deterministic category/risk-stratified v0.6 train/validation splits."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

from build_v06_dataset import (
    DEFAULT_GENERATED_DIR,
    DatasetV06Error,
    _display_path,
    atomic_write_text,
    jsonl_text,
)


DEFAULT_SEED = "gaialab-naija-v0.6"
DEFAULT_VALIDATION_FRACTION = 0.2


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise DatasetV06Error(f"Dataset file not found: {_display_path(path)}")
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetV06Error(
                    f"{_display_path(path)}:{line_number}: invalid JSON."
                ) from exc
            records.append(record)
    if not records:
        raise DatasetV06Error(f"Dataset is empty: {_display_path(path)}")
    return records


def _rank(record: dict[str, Any], seed: str) -> str:
    value = f"{seed}\0{record['category']}\0{record['risk_level']}\0{record['id']}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stratified_split(
    records: list[dict[str, Any]],
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    seed: str = DEFAULT_SEED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not 0 < validation_fraction < 1:
        raise DatasetV06Error("validation_fraction must be between 0 and 1.")
    strata: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        try:
            strata[(record["category"], record["risk_level"])].append(record)
        except KeyError as exc:
            raise DatasetV06Error(f"Record missing split field: {exc.args[0]}") from exc

    training: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    for key in sorted(strata):
        group = sorted(strata[key], key=lambda record: (_rank(record, seed), record["id"]))
        validation_count = 0
        if len(group) >= 2:
            validation_count = max(1, math.floor(len(group) * validation_fraction))
            validation_count = min(validation_count, len(group) - 1)
        validation.extend(group[:validation_count])
        training.extend(group[validation_count:])

    return (
        sorted(training, key=lambda record: record["id"]),
        sorted(validation, key=lambda record: record["id"]),
    )


def write_splits(
    input_path: Path,
    generated_dir: Path,
    validation_fraction: float = DEFAULT_VALIDATION_FRACTION,
    seed: str = DEFAULT_SEED,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records = load_jsonl(input_path)
    training, validation = stratified_split(records, validation_fraction, seed)
    training_path = generated_dir / "v0.6_training.jsonl"
    validation_path = generated_dir / "v0.6_validation.jsonl"
    atomic_write_text(training_path, jsonl_text(training))
    atomic_write_text(validation_path, jsonl_text(validation))

    manifest_path = generated_dir / "dataset_manifest.json"
    if not manifest_path.is_file():
        raise DatasetV06Error(
            f"Manifest file not found: {_display_path(manifest_path)}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise DatasetV06Error("dataset_manifest.json contains invalid JSON.") from exc
    manifest["outputs"].update(
        {
            "training": _display_path(training_path),
            "validation": _display_path(validation_path),
        }
    )
    manifest["split"] = {
        "algorithm": "sha256_rank_within_category_and_risk_level",
        "seed": seed,
        "requested_validation_fraction": validation_fraction,
        "training_records": len(training),
        "validation_records": len(validation),
        "singleton_strata_policy": "training",
        "multi_record_strata_policy": "at_least_one_record_in_each_split",
    }
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        backup=False,
    )
    return training, validation


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, default=DEFAULT_GENERATED_DIR / "v0.6_all.jsonl"
    )
    parser.add_argument("--generated-dir", type=Path, default=DEFAULT_GENERATED_DIR)
    parser.add_argument(
        "--validation-fraction", type=float, default=DEFAULT_VALIDATION_FRACTION
    )
    parser.add_argument("--seed", default=DEFAULT_SEED)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        training, validation = write_splits(
            args.input, args.generated_dir, args.validation_fraction, args.seed
        )
    except (DatasetV06Error, OSError) as exc:
        print(f"v0.6 split failed: {exc}")
        return 1
    print(f"Wrote {len(training)} training and {len(validation)} validation records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

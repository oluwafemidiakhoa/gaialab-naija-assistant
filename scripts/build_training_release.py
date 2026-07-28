"""Build a write-once, eligibility-enforced dataset release candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import atomic_create, file_sha256, read_jsonl
from src.training_eligibility import (
    assess_eligibility, assert_no_benchmark_leakage, canonical_hash,
    decisions_json, deterministic_splits,
)


def build(source: str, target: str, output_root: Path, dry_run: bool) -> dict:
    release = Path("data/releases") / source
    records = read_jsonl(release / f"{source}.jsonl")
    manifest_path = release / "dataset_manifest.json"
    decisions = [assess_eligibility(record, source) for record in records]
    eligible_ids = {d.record_id for d in decisions if d.eligible}
    eligible = [record for record in records if record["id"] in eligible_ids]
    splits = deterministic_splits(eligible)
    assert_no_benchmark_leakage(splits)
    summary = {
        "source_version": source,
        "target_version": target,
        "release_status": "candidate",
        "source_manifest_sha256": file_sha256(manifest_path),
        "record_count": len(records),
        "eligible_count": len(eligible),
        "excluded_count": len(records) - len(eligible),
        "dry_run": dry_run,
    }
    if dry_run:
        return summary
    destination = output_root / target
    if destination.exists():
        raise FileExistsError(f"release candidate already exists: {destination}")
    destination.mkdir(parents=True)
    for name, rows in splits.items():
        atomic_create(
            destination / f"{name}.jsonl",
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        )
    eligible_decisions = [d for d in decisions if d.eligible]
    excluded_decisions = [d for d in decisions if not d.eligible]
    atomic_create(destination / "eligibility_report.json", json.dumps(
        decisions_json(eligible_decisions), indent=2, sort_keys=True
    ) + "\n")
    atomic_create(destination / "exclusion_report.json", json.dumps(
        decisions_json(excluded_decisions), indent=2, sort_keys=True
    ) + "\n")
    split_manifest = {
        name: {"count": len(rows), "sha256": file_sha256(destination / f"{name}.jsonl")}
        for name, rows in splits.items()
    }
    atomic_create(destination / "split_manifest.json", json.dumps(
        split_manifest, indent=2, sort_keys=True
    ) + "\n")
    candidate = {**summary, "splits": split_manifest}
    candidate["release_candidate_sha256"] = canonical_hash(candidate)
    atomic_create(destination / "release_candidate_manifest.json", json.dumps(
        candidate, indent=2, sort_keys=True
    ) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-version", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("data/release_candidates"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(build(
            args.source_version, args.target_version, args.output_root, args.dry_run
        ), indent=2, sort_keys=True))
    except (OSError, ValueError) as exc:
        print(f"Training release failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

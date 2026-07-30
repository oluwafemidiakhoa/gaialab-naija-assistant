"""Build a write-once, eligibility-enforced dataset release candidate."""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import atomic_create, file_sha256, read_jsonl
from src.training_eligibility import (
    assess_eligibility,
    assert_no_benchmark_leakage,
    canonical_hash,
    decisions_json,
    deterministic_splits,
)


def read_audit_events(path: Path) -> list[dict[str, Any]]:
    """Read JSONL or JSON audit events from one file."""
    events: list[dict[str, Any]] = []

    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return events

    if not text:
        return events

    if path.suffix.casefold() == ".jsonl":
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(payload, dict):
                events.append(payload)

        return events

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return events

    if isinstance(payload, dict):
        events.append(payload)
    elif isinstance(payload, list):
        events.extend(item for item in payload if isinstance(item, dict))

    return events


def load_latest_review_states(
    audit_root: Path,
    release_version: str,
) -> dict[str, dict[str, Any]]:
    """Return the latest valid review event for every record."""
    version_root = audit_root / release_version

    if not version_root.exists():
        return {}

    latest: dict[str, dict[str, Any]] = {}

    for path in sorted(version_root.rglob("*.json*")):
        for event in read_audit_events(path):
            if event.get("dataset_version") != release_version:
                continue

            if event.get("event_type") != "human_decision":
                continue

            record_id = str(event.get("record_id", "")).strip()
            new_status = str(event.get("new_status", "")).strip()
            timestamp = str(event.get("timestamp", "")).strip()

            if not record_id or not new_status or not timestamp:
                continue

            current = latest.get(record_id)
            current_timestamp = (
                str(current.get("timestamp", ""))
                if current
                else ""
            )

            if current is None or timestamp > current_timestamp:
                latest[record_id] = event

    return latest


def apply_effective_review_state(
    record: dict[str, Any],
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    """Overlay a valid audit-ledger review state without mutating source data."""
    effective = deepcopy(record)

    if not event:
        return effective

    record_id = str(record.get("id", ""))
    event_record_id = str(event.get("record_id", ""))

    if event_record_id != record_id:
        return effective

    record_hash = str(record.get("example_sha256", ""))
    event_hash = str(event.get("record_sha256", ""))

    if not record_hash or event_hash != record_hash:
        return effective

    status = str(event.get("new_status", "")).strip()

    if not status:
        return effective

    effective["review_status"] = status

    if status in {
        "technical_reviewed",
        "domain_reviewed",
        "approved",
    }:
        effective["technical_review_completed"] = True

    return effective


def build(
    source: str,
    target: str,
    output_root: Path,
    audit_root: Path,
    dry_run: bool,
) -> dict[str, Any]:
    release = Path("data/releases") / source
    records = read_jsonl(release / f"{source}.jsonl")
    manifest_path = release / "dataset_manifest.json"

    review_states = load_latest_review_states(
        audit_root,
        source,
    )

    effective_records = [
        apply_effective_review_state(
            record,
            review_states.get(str(record.get("id", ""))),
        )
        for record in records
    ]

    decisions = [
        assess_eligibility(record, source)
        for record in effective_records
    ]

    eligible_ids = {
        decision.record_id
        for decision in decisions
        if decision.eligible
    }

    eligible = [
        record
        for record in records
        if record["id"] in eligible_ids
    ]

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
        "review_event_count": len(review_states),
        "dry_run": dry_run,
    }

    if dry_run:
        return summary

    destination = output_root / target

    if destination.exists():
        raise FileExistsError(
            f"release candidate already exists: {destination}"
        )

    destination.mkdir(parents=True)

    for name, rows in splits.items():
        atomic_create(
            destination / f"{name}.jsonl",
            "".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
                for row in rows
            ),
        )

    eligible_decisions = [
        decision
        for decision in decisions
        if decision.eligible
    ]

    excluded_decisions = [
        decision
        for decision in decisions
        if not decision.eligible
    ]

    atomic_create(
        destination / "eligibility_report.json",
        json.dumps(
            decisions_json(eligible_decisions),
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    atomic_create(
        destination / "exclusion_report.json",
        json.dumps(
            decisions_json(excluded_decisions),
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    split_manifest = {
        name: {
            "count": len(rows),
            "sha256": file_sha256(
                destination / f"{name}.jsonl"
            ),
        }
        for name, rows in splits.items()
    }

    atomic_create(
        destination / "split_manifest.json",
        json.dumps(
            split_manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    candidate = {
        **summary,
        "splits": split_manifest,
    }

    candidate["release_candidate_sha256"] = canonical_hash(
        candidate
    )

    atomic_create(
        destination / "release_candidate_manifest.json",
        json.dumps(
            candidate,
            indent=2,
            sort_keys=True,
        )
        + "\n",
    )

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--source-version",
        required=True,
    )

    parser.add_argument(
        "--target-version",
        required=True,
    )

    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/release_candidates"),
    )

    parser.add_argument(
        "--audit-root",
        type=Path,
        default=Path("evaluation/review_audit"),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
    )

    args = parser.parse_args()

    try:
        result = build(
            args.source_version,
            args.target_version,
            args.output_root,
            args.audit_root,
            args.dry_run,
        )

        print(
            json.dumps(
                result,
                indent=2,
                sort_keys=True,
            )
        )

    except (OSError, ValueError) as exc:
        print(
            f"Training release failed: {exc}",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
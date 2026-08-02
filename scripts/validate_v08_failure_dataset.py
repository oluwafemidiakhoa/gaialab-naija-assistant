"""Validate v0.8 drafts, role/state metadata, duplicates, and governance gates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import read_jsonl  # noqa: E402
from src.v08_failure_dataset import (  # noqa: E402
    cross_version_prompt_duplicates,
    load_previous_records,
    validate_records,
)

DEFAULT_INPUT = ROOT / "data" / "v0.8" / "generated" / "v0.8_draft.jsonl"
DEFAULT_PRIOR = (ROOT / "data" / "releases" / "v0.6" / "v0.6.jsonl",)


def validate(path: Path, prior_paths: tuple[Path, ...] = DEFAULT_PRIOR) -> dict[str, object]:
    records = read_jsonl(path)
    report = validate_records(records)
    report["cross_version_duplicate_prompts"] = cross_version_prompt_duplicates(
        records, load_previous_records(prior_paths)
    )
    if report["cross_version_duplicate_prompts"]:
        report["valid"] = False
        report["errors"].append(
            f"cross-version duplicate prompts: {len(report['cross_version_duplicate_prompts'])}"
        )
    report["training_release_allowed"] = False
    report["training_release_refusal_reason"] = (
        "All v0.8 records are drafts and require explicit human review and approval."
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--prior", type=Path, action="append")
    args = parser.parse_args(argv)
    try:
        report = validate(args.input, tuple(args.prior) if args.prior else DEFAULT_PRIOR)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["valid"] else 1
    except (OSError, ValueError) as exc:
        print(f"v0.8 validation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

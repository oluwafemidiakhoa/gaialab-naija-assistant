"""Create write-once cross-version reports from human-scored benchmark results."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.benchmarking import report_files
from src.dataset_management import atomic_create, read_jsonl


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-root", type=Path, default=Path("evaluation/reports"))
    args = parser.parse_args()
    destination = args.output_root / args.run_id
    try:
        if destination.exists():
            raise FileExistsError(f"benchmark report exists: {destination}")
        for name, text in report_files(read_jsonl(args.results)).items():
            atomic_create(destination / name, text)
        print(destination)
    except (OSError, ValueError) as exc:
        print(f"Benchmark report failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

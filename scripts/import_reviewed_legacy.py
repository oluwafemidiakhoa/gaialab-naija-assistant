"""Import supported, explicitly human-approved legacy provenance rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.legacy_provenance import LegacyProvenanceError, import_reviewed, utc_stamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "review_sheets",
        nargs="*",
        type=Path,
        default=[
            Path("data/legacy_review/v0.4_provenance_review.csv"),
            Path("data/legacy_review/v0.5_provenance_review.csv"),
        ],
    )
    parser.add_argument("--registry", type=Path, default=Path("data/registry"))
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    report_dir = args.report_dir or Path("data/legacy_review/migrations") / utc_stamp()
    try:
        report = import_reviewed(
            args.review_sheets, args.registry, report_dir
        )
    except (LegacyProvenanceError, OSError) as exc:
        print(f"Legacy import failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"Migration report: {report_dir / 'migration_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

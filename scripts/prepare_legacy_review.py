"""Create write-once v0.4/v0.5 provenance review sheets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.legacy_provenance import LegacyProvenanceError, write_review_sheets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("data/legacy_review"))
    args = parser.parse_args()
    try:
        outputs = write_review_sheets(args.output_dir)
    except (LegacyProvenanceError, OSError) as exc:
        print(f"Legacy review preparation failed: {exc}", file=sys.stderr)
        return 1
    for version, path in outputs.items():
        print(f"{version}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

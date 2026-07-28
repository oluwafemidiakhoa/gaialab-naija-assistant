"""Audit legacy v0.4/v0.5 provenance without proposing unsupported values."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import atomic_create
from src.legacy_provenance import LegacyProvenanceError, audit_all


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = audit_all()
        text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            atomic_create(args.output, text)
        print(text, end="")
    except (LegacyProvenanceError, OSError, subprocess.SubprocessError) as exc:
        print(f"Legacy provenance audit failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

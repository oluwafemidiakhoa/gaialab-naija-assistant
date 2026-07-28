"""Build a local Hugging Face dataset package; never upload it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.huggingface_export import ExportError, export_package


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--include-drafts", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(export_package(
            args.version, args.output_dir, include_drafts=args.include_drafts
        ), indent=2, sort_keys=True))
    except (OSError, ValueError, ExportError) as exc:
        print(f"Hugging Face export failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

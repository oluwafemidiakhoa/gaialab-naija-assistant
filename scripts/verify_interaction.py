#!/usr/bin/env python3
"""Verify one GaiaLab AI interaction from a JSON file or stdin."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.trust_engine import verify_interaction  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GaiaLab Naija Trust Engine MVP")
    parser.add_argument("path", nargs="?", help="JSON input path. Omit to read stdin.")
    args = parser.parse_args()

    if args.path:
        payload = json.loads(Path(args.path).read_text(encoding="utf-8"))
    else:
        payload = json.load(sys.stdin)

    json.dump(verify_interaction(payload), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

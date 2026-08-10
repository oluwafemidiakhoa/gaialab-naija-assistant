"""Stage synthetic Nigerian-language trust fixtures as draft human-review candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.language_governance import stage_trust_fixture_records


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number}: expected object")
            rows.append(value)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("evaluation/fixtures/naija_pidgin_trust_v0.1.jsonl"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.output.exists():
            raise FileExistsError(f"refusing to overwrite existing file: {args.output}")
        rows = _read_jsonl(args.input)
        staged = stage_trust_fixture_records(rows, source_path=args.input.as_posix())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in staged),
            encoding="utf-8",
        )
        print(json.dumps({
            "input": args.input.as_posix(),
            "output": args.output.as_posix(),
            "record_count": len(staged),
            "review_status": "draft",
            "culturally_validated": False,
            "training_eligible": False,
        }, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Language review staging failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

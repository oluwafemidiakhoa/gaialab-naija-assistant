"""Generate benchmark responses for transparent human review (no claimed scores)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.app import respond


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results.jsonl"))
    parser.add_argument("--max-new-tokens", type=int, default=192)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.benchmark.open(encoding="utf-8") as source, args.output.open(
        "w", encoding="utf-8"
    ) as destination:
        for line in source:
            if not line.strip():
                continue
            case = json.loads(line)
            result = {
                **case,
                "response": respond(
                    case["instruction"], case["mode"], args.max_new_tokens
                ),
                "human_review": {"passed_checks": [], "notes": ""},
            }
            destination.write(json.dumps(result, ensure_ascii=False) + "\n")
    print(f"Wrote unscored responses to {args.output}. Complete human_review manually.")


if __name__ == "__main__":
    main()

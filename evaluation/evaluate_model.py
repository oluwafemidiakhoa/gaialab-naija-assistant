"""Generate benchmark responses for transparent human review (no claimed scores)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.app import generate_response, get_configured_model_id


def evaluate(
    benchmark: Path, output: Path, max_new_tokens: int, model_id: str
) -> None:
    """Generate every response successfully before atomically writing results."""
    if not benchmark.is_file():
        raise FileNotFoundError(f"Benchmark file not found: {benchmark}")

    results = []
    with benchmark.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Benchmark line {line_number} contains invalid JSON: {exc.msg}."
                ) from exc
            missing = {"id", "instruction", "mode", "category", "checks"} - set(case)
            if missing:
                raise ValueError(
                    f"Benchmark line {line_number} is missing: "
                    f"{', '.join(sorted(missing))}."
                )
            results.append(
                {
                    **case,
                    "response": generate_response(
                        case["instruction"], case["mode"], max_new_tokens
                    ),
                    "model_id": model_id,
                    "human_review": {"passed_checks": [], "notes": ""},
                }
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    with temporary_output.open("w", encoding="utf-8") as destination:
        for result in results:
            destination.write(json.dumps(result, ensure_ascii=False) + "\n")
    temporary_output.replace(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", type=Path, default=Path("evaluation/benchmark.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results.jsonl"))
    parser.add_argument("--max-new-tokens", type=int, default=192)
    args = parser.parse_args()

    try:
        model_id = get_configured_model_id()
        evaluate(args.benchmark, args.output, args.max_new_tokens, model_id)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote unscored responses to {args.output}. Complete human_review manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

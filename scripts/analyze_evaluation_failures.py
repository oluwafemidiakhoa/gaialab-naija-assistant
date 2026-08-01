"""Summarize evidence-backed v0.7.0-rc.3 evaluation classifications and failures."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import read_jsonl  # noqa: E402
from src.v08_failure_dataset import FAILURE_TAXONOMY, write_once_or_verify  # noqa: E402

DEFAULT_INPUT = ROOT / "evaluation" / "v0.7.0-rc.3" / "first_adapter_evaluation.jsonl"
DEFAULT_OUTPUT = ROOT / "data" / "v0.8" / "generated" / "evaluation_failure_analysis.json"
EXPECTED_RESULTS = {
    "eval-001": "borderline", "eval-002": "fail", "eval-003": "pass",
    "eval-004": "fail", "eval-005": "pass", "eval-006": "pass",
    "eval-007": "fail", "eval-008": "fail", "eval-009": "pass",
    "eval-010": "borderline",
}


def analyze(input_path: Path) -> dict[str, object]:
    rows = read_jsonl(input_path)
    ids = [str(row.get("evaluation_id", "")) for row in rows]
    errors = []
    if len(rows) != 10 or set(ids) != set(EXPECTED_RESULTS):
        errors.append("evaluation source must contain eval-001 through eval-010 exactly once")
    for row in rows:
        evaluation_id = str(row.get("evaluation_id", ""))
        if EXPECTED_RESULTS.get(evaluation_id) != row.get("result"):
            errors.append(f"{evaluation_id}: incorrect supplied classification")
        unknown = set(row.get("failure_types", [])) - set(FAILURE_TAXONOMY)
        if unknown:
            errors.append(f"{evaluation_id}: unknown failure types {sorted(unknown)}")
    missing = [
        row["evaluation_id"] for row in rows
        if row.get("prompt") is None or row.get("model_response") is None
    ]
    return {
        "adapter_version": "v0.7.0-rc.3",
        "evaluation_count": len(rows),
        "classification_counts": dict(sorted(Counter(row.get("result") for row in rows).items())),
        "failure_type_counts": dict(sorted(Counter(
            label for row in rows for label in row.get("failure_types", [])
        ).items())),
        "transcript_evidence_complete": not missing,
        "missing_transcript_evidence": missing,
        "evidence_warning": (
            "Exact prompts and model responses were not supplied; summaries were not promoted to transcripts."
            if missing else ""
        ),
        "valid_classifications": not errors,
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        report = analyze(args.input)
        text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        status = write_once_or_verify(args.output, text)
        print(json.dumps({**report, "output": str(args.output), "output_status": status}, indent=2, sort_keys=True))
        return 0 if report["valid_classifications"] else 1
    except (OSError, ValueError) as exc:
        print(f"evaluation analysis failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Create reproducible reports from existing human-reviewed benchmark results."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCORE_FIELDS = (
    "instruction_following",
    "meaning_preservation",
    "naturalness",
    "professional_tone",
    "safety",
    "business_usefulness",
    "factual_consistency",
    "tone",
    "clarity",
)


class BenchmarkReportError(ValueError):
    pass


def read_results(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise BenchmarkReportError(f"{path}:{number}: invalid JSON") from exc
                if not isinstance(record, dict):
                    raise BenchmarkReportError(f"{path}:{number}: expected object")
                copy = dict(record)
                copy["_source_file"] = str(path)
                records.append(copy)
    return records


def model_name(record: dict[str, Any]) -> str:
    return str(
        record.get("model_version")
        or record.get("model_id")
        or record.get("model")
        or "unknown"
    )


def _review(record: dict[str, Any]) -> dict[str, Any]:
    nested = record.get("human_review")
    return nested if isinstance(nested, dict) else record


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_model[model_name(record)].append(record)
    models: dict[str, Any] = {}
    for model in sorted(by_model):
        values = by_model[model]
        score_lists: dict[str, list[float]] = defaultdict(list)
        reviewed = 0
        for record in values:
            review = _review(record)
            has_score = False
            for field in SCORE_FIELDS:
                score = review.get(field)
                if isinstance(score, (int, float)) and not isinstance(score, bool):
                    score_lists[field].append(float(score))
                    has_score = True
            reviewed += int(has_score)
        models[model] = {
            "responses": len(values),
            "human_reviewed_responses": reviewed,
            "mean_human_scores": {
                field: round(statistics.fmean(scores), 4)
                for field, scores in sorted(score_lists.items())
            },
            "source_files": sorted({record["_source_file"] for record in values}),
        }
    return {
        "model_count": len(models),
        "models": models,
        "scoring_policy": (
            "Only numeric scores already entered by human reviewers are aggregated; "
            "missing scores remain missing."
        ),
    }


def markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# GaiaBench cross-version report",
        "",
        "> Draft benchmark report pending independent human review. No scores are assigned automatically.",
        "",
        "| Model | Responses | Human-reviewed | Mean human scores |",
        "| --- | ---: | ---: | --- |",
    ]
    for model, values in summary["models"].items():
        scores = ", ".join(
            f"{field}={score}" for field, score in values["mean_human_scores"].items()
        ) or "—"
        lines.append(
            f"| {model} | {values['responses']} | "
            f"{values['human_reviewed_responses']} | {scores} |"
        )
    lines.extend(["", summary["scoring_policy"], ""])
    return "\n".join(lines)


def write_report(
    inputs: list[Path], output_dir: Path, report_id: str | None = None
) -> dict[str, Path]:
    if not inputs:
        raise BenchmarkReportError("no benchmark result files supplied")
    summary = summarize(read_results(inputs))
    identifier = report_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    if not identifier.replace("-", "").replace("_", "").isalnum():
        raise BenchmarkReportError("report_id contains unsafe characters")
    report_dir = output_dir / identifier
    if report_dir.exists():
        raise BenchmarkReportError(f"report already exists: {report_dir}")
    report_dir.mkdir(parents=True)
    json_path = report_dir / "all_model_versions.json"
    markdown_path = report_dir / "all_model_versions.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown(summary), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="*",
        type=Path,
        help="Result JSONL files. If omitted, all JSONL files in --results-dir are used.",
    )
    parser.add_argument(
        "--results-dir", type=Path, default=Path("evaluation/results")
    )
    parser.add_argument("--output-dir", type=Path, default=Path("evaluation/reports"))
    parser.add_argument("--report-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        inputs = args.inputs or sorted(args.results_dir.glob("*.jsonl"))
        outputs = write_report(inputs, args.output_dir, args.report_id)
    except (BenchmarkReportError, OSError) as exc:
        print(f"Benchmark report failed: {exc}")
        return 1
    print("\n".join(f"{name}: {path}" for name, path in outputs.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

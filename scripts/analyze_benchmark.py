from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from benchmark_rules import evaluate_case


REVIEW_FIELDS = [
    "instruction_following",
    "factual_consistency",
    "tone",
    "clarity",
    "safety",
    "hallucination",
    "pass",
    "reviewer_notes",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score GaiaLab benchmark responses."
    )

    parser.add_argument(
        "--input",
        default="evaluation/v0.4/v0.3_baseline_review.csv",
    )

    parser.add_argument(
        "--output",
        default="evaluation/v0.4/v0.3_baseline_review_auto_scored.csv",
    )

    parser.add_argument(
        "--metrics",
        default="evaluation/v0.4/v0.3_metrics.json",
    )

    parser.add_argument(
        "--summary",
        default="evaluation/v0.4/v0.3_summary.md",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    metrics_path = Path(args.metrics)
    summary_path = Path(args.summary)

    if not input_path.exists():
        raise FileNotFoundError(
            f"Benchmark output not found: {input_path}"
        )

    with input_path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        rows = list(reader)
        fields = list(reader.fieldnames or [])

    for field in REVIEW_FIELDS:
        if field not in fields:
            fields.append(field)

    reviewed_rows: list[dict[str, str]] = []

    for index, row in enumerate(rows, start=1):
        benchmark_id = row.get("id", "")
        response = row.get("model_response", "")

        evaluation = evaluate_case(
            benchmark_id,
            response,
        )

        row.update(evaluation)
        reviewed_rows.append(row)

        print(
            f"[{index}/{len(rows)}] "
            f"{benchmark_id} -> {evaluation['pass']}"
        )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
        )
        writer.writeheader()
        writer.writerows(reviewed_rows)

    total = len(reviewed_rows)
    passed = sum(
        row["pass"] == "Pass"
        for row in reviewed_rows
    )
    failed = sum(
        row["pass"] == "Fail"
        for row in reviewed_rows
    )
    needs_review = sum(
        row["pass"] == "Needs review"
        for row in reviewed_rows
    )

    category_totals = Counter(
        row.get("category", "unknown")
        for row in reviewed_rows
    )

    category_passes = Counter(
        row.get("category", "unknown")
        for row in reviewed_rows
        if row["pass"] == "Pass"
    )

    hallucinations = Counter(
        row["hallucination"]
        for row in reviewed_rows
    )

    metrics = {
        "model_version": (
            reviewed_rows[0].get("model_version", "unknown")
            if reviewed_rows
            else "unknown"
        ),
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "needs_review": needs_review,
        "automatic_pass_rate": (
            round(passed / total, 4)
            if total
            else 0
        ),
        "scored_case_pass_rate": (
            round(passed / (passed + failed), 4)
            if passed + failed
            else 0
        ),
        "hallucinations": dict(hallucinations),
        "category_totals": dict(category_totals),
        "category_passes": dict(category_passes),
    }

    metrics_path.write_text(
        json.dumps(metrics, indent=2),
        encoding="utf-8",
    )

    report = [
        "# GaiaLab Benchmark Report",
        "",
        f"- Model version: {metrics['model_version']}",
        f"- Total cases: {total}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        f"- Needs human review: {needs_review}",
        (
            f"- Automatic pass rate: "
            f"{metrics['automatic_pass_rate']:.1%}"
        ),
        (
            f"- Pass rate among automatically scored cases: "
            f"{metrics['scored_case_pass_rate']:.1%}"
        ),
        "",
        "## Results by category",
        "",
        "| Category | Cases | Passed | Pass rate |",
        "|---|---:|---:|---:|",
    ]

    for category in sorted(category_totals):
        cases = category_totals[category]
        category_passed = category_passes[category]
        rate = category_passed / cases if cases else 0

        report.append(
            f"| {category} | {cases} | "
            f"{category_passed} | {rate:.1%} |"
        )

    report.extend(
        [
            "",
            "## Hallucination results",
            "",
        ]
    )

    for label, count in sorted(hallucinations.items()):
        report.append(f"- {label}: {count}")

    report.extend(
        [
            "",
            "> Cases marked Needs review do not yet have "
            "a benchmark-specific automatic rule.",
            "",
        ]
    )

    summary_path.write_text(
        "\n".join(report),
        encoding="utf-8",
    )

    print()
    print("Evaluation complete.")
    print(f"Scored CSV: {output_path}")
    print(f"Metrics: {metrics_path}")
    print(f"Report: {summary_path}")


if __name__ == "__main__":
    main()
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare two GaiaLab benchmark metric files."
    )

    parser.add_argument(
        "--baseline",
        required=True,
        help="Path to the baseline metrics JSON file.",
    )

    parser.add_argument(
        "--candidate",
        required=True,
        help="Path to the candidate metrics JSON file.",
    )

    parser.add_argument(
        "--output",
        default="evaluation/v0.4/model_comparison.md",
        help="Path for the generated comparison report.",
    )

    return parser.parse_args()


def load_metrics(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Metrics file not found: {path}")

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in metrics file: {path}"
        ) from exc


def get_pass_rate(metrics: dict) -> float:
    if "scored_case_pass_rate" in metrics:
        return float(metrics["scored_case_pass_rate"])

    if "automatic_pass_rate" in metrics:
        return float(metrics["automatic_pass_rate"])

    if "pass_rate" in metrics:
        return float(metrics["pass_rate"])

    total = int(metrics.get("total_cases", 0))
    passed = int(metrics.get("passed", 0))

    return passed / total if total else 0.0


def format_percent(value: float) -> str:
    return f"{value:.1%}"


def main() -> None:
    args = parse_args()

    baseline_path = Path(args.baseline)
    candidate_path = Path(args.candidate)
    output_path = Path(args.output)

    baseline = load_metrics(baseline_path)
    candidate = load_metrics(candidate_path)

    baseline_rate = get_pass_rate(baseline)
    candidate_rate = get_pass_rate(candidate)
    rate_change = candidate_rate - baseline_rate

    baseline_failed = int(baseline.get("failed", 0))
    candidate_failed = int(candidate.get("failed", 0))
    failed_change = candidate_failed - baseline_failed

    baseline_review = int(baseline.get("needs_review", 0))
    candidate_review = int(candidate.get("needs_review", 0))
    review_change = candidate_review - baseline_review

    if rate_change > 0:
        verdict = "Improved"
        explanation = (
            "The candidate model achieved a higher benchmark pass rate "
            "than the baseline."
        )
    elif rate_change < 0:
        verdict = "Regressed"
        explanation = (
            "The candidate model achieved a lower benchmark pass rate "
            "than the baseline and should not replace it yet."
        )
    else:
        verdict = "No measurable change"
        explanation = (
            "The candidate and baseline models achieved the same "
            "benchmark pass rate."
        )

    lines = [
        "# GaiaLab Model Comparison",
        "",
        f"- Baseline metrics: `{baseline_path}`",
        f"- Candidate metrics: `{candidate_path}`",
        "",
        "| Metric | Baseline | Candidate | Change |",
        "|---|---:|---:|---:|",
        (
            f"| Model version | "
            f"{baseline.get('model_version', 'unknown')} | "
            f"{candidate.get('model_version', 'unknown')} | — |"
        ),
        (
            f"| Pass rate | "
            f"{format_percent(baseline_rate)} | "
            f"{format_percent(candidate_rate)} | "
            f"{rate_change:+.1%} |"
        ),
        (
            f"| Passed cases | "
            f"{baseline.get('passed', 0)} | "
            f"{candidate.get('passed', 0)} | "
            f"{int(candidate.get('passed', 0)) - int(baseline.get('passed', 0)):+d} |"
        ),
        (
            f"| Failed cases | "
            f"{baseline_failed} | "
            f"{candidate_failed} | "
            f"{failed_change:+d} |"
        ),
        (
            f"| Needs review | "
            f"{baseline_review} | "
            f"{candidate_review} | "
            f"{review_change:+d} |"
        ),
        "",
        f"## Verdict: {verdict}",
        "",
        explanation,
        "",
    ]

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("Model comparison completed.")
    print(f"Baseline: {baseline_path}")
    print(f"Candidate: {candidate_path}")
    print(f"Pass-rate change: {rate_change:+.1%}")
    print(f"Verdict: {verdict}")
    print(f"Report: {output_path}")


if __name__ == "__main__":
    main()
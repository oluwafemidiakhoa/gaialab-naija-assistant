"""Version-comparable benchmark schema, leakage checks, and reports."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from typing import Any, Iterable

DIMENSIONS = (
    "task_completion", "relevance", "clarity", "safety",
    "nigerian_context_appropriateness", "nigerian_pidgin_quality",
    "business_writing_quality", "refusal_correctness", "hallucination_risk",
    "credential_protection_behavior", "high_risk_escalation_behavior",
)


def canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


def prepare_benchmark_case(case: dict[str, Any]) -> dict[str, Any]:
    required = {
        "benchmark_id", "category", "risk_level", "prompt", "expected_behaviors",
        "prohibited_behaviors", "scoring_rubric", "benchmark_version",
    }
    missing = sorted(required - case.keys())
    if missing:
        raise ValueError(f"missing benchmark fields: {', '.join(missing)}")
    prepared = {key: case[key] for key in sorted(required)}
    prepared["benchmark_sha256"] = canonical_hash(prepared)
    return prepared


def _normalize(text: str) -> str:
    return " ".join("".join(
        character if character.isalnum() else " " for character in text.casefold()
    ).split())


def leakage_report(
    cases: Iterable[dict[str, Any]], training_records: Iterable[dict[str, Any]],
    near_threshold: float = 0.8,
) -> dict[str, Any]:
    cases_list = list(cases)
    training = list(training_records)
    train_ids = {str(row.get("id", "")) for row in training}
    train_prompts = {
        _normalize(row["messages"][1]["content"]): row.get("id") for row in training
    }
    id_overlap = sorted(
        case["benchmark_id"] for case in cases_list if case["benchmark_id"] in train_ids
    )
    exact_overlap = sorted(
        case["benchmark_id"] for case in cases_list
        if _normalize(case["prompt"]) in train_prompts
    )
    near = []
    for case in cases_list:
        left = set(_normalize(case["prompt"]).split())
        for prompt, record_id in train_prompts.items():
            right = set(prompt.split())
            similarity = len(left & right) / len(left | right) if left | right else 0
            if near_threshold <= similarity < 1:
                near.append({
                    "benchmark_id": case["benchmark_id"], "record_id": record_id,
                    "similarity": round(similarity, 4),
                })
    return {
        "benchmark_id_overlap": id_overlap,
        "exact_prompt_overlap": exact_overlap,
        "normalized_prompt_overlap": exact_overlap,
        "near_duplicate_overlap": sorted(near, key=lambda row: (row["benchmark_id"], row["record_id"])),
        "leakage_free": not id_overlap and not exact_overlap,
    }


def aggregate_results(results: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(results)
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_model[row["model_version"]].append(row)
    models = {}
    for version, values in sorted(by_model.items()):
        passed = sum(bool(value.get("passed")) for value in values)
        safety_values = [value for value in values if "safety_passed" in value]
        categories = Counter()
        category_passes = Counter()
        for value in values:
            categories[value["category"]] += 1
            category_passes[value["category"]] += bool(value.get("passed"))
        models[version] = {
            "case_count": len(values),
            "overall_pass_rate": round(100 * passed / len(values), 2) if values else 0,
            "safety_pass_rate": round(
                100 * sum(bool(v["safety_passed"]) for v in safety_values) / len(safety_values), 2
            ) if safety_values else None,
            "per_category": {
                category: round(100 * category_passes[category] / count, 2)
                for category, count in sorted(categories.items())
            },
            "dataset_version": values[0].get("dataset_version"),
            "model_verified": all(v.get("model_verified", False) for v in values),
            "benchmark_version": values[0].get("benchmark_version"),
            "scoring_method": values[0].get("scoring_method"),
        }
    return {"models": models, "comparable": len({
        (v.get("benchmark_version"), v.get("scoring_method")) for v in rows
    }) <= 1}


def report_files(results: list[dict[str, Any]]) -> dict[str, str]:
    summary = aggregate_results(results)
    markdown = "# Cross-version benchmark\n\n"
    if not summary["comparable"]:
        markdown += "> Results are not directly comparable because methods differ.\n\n"
    for version, values in summary["models"].items():
        markdown += f"- {version}: {values['overall_pass_rate']}% overall pass rate\n"
    category_buffer = io.StringIO()
    writer = csv.writer(category_buffer, lineterminator="\n")
    writer.writerow(["model_version", "category", "pass_rate"])
    for version, values in summary["models"].items():
        for category, rate in values["per_category"].items():
            writer.writerow([version, category, rate])
    failure_buffer = io.StringIO()
    fieldnames = ["model_version", "benchmark_id", "category", "failure_reason"]
    failure_writer = csv.DictWriter(failure_buffer, fieldnames=fieldnames, lineterminator="\n")
    failure_writer.writeheader()
    for row in results:
        if not row.get("passed"):
            failure_writer.writerow({key: row.get(key, "") for key in fieldnames})
    return {
        "all_model_versions.json": json.dumps(summary, indent=2, sort_keys=True) + "\n",
        "all_model_versions.md": markdown,
        "per_category.csv": category_buffer.getvalue(),
        "failures.csv": failure_buffer.getvalue(),
    }

"""Public, deterministic dataset release scorecards."""

from __future__ import annotations

import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from src.dataset_management import file_sha256, utc_now
from src.training_eligibility import EligibilityDecision, canonical_hash


def _distribution(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(r.get(field) or "unknown") for r in records).items()))


def generate_scorecard(
    release_version: str,
    records: Iterable[dict[str, Any]],
    manifest_path: Path,
    *,
    decisions: Iterable[EligibilityDecision] = (),
    assessments: Iterable[dict[str, Any]] = (),
    duplicate_count: int = 0,
    benchmark_coverage: float = 0.0,
    generated_at: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    rows = list(records)
    decision_rows = list(decisions)
    assessments_list = list(assessments)
    scores = [int(a["overall_score"]) for a in assessments_list if a.get("overall_score") is not None]
    statuses = Counter(r.get("review_status", "draft") for r in rows)
    total = len(rows)
    technical = sum(bool(
        r.get("technical_review_completed")
        or r.get("review_status") in {"technical_reviewed", "domain_reviewed", "approved"}
    ) for r in rows)
    domain_required = [r for r in rows if r.get("category") in {
        "healthcare", "banking", "government_services"
    }]
    domain_done = sum(bool(
        r.get("domain_review_completed") or r.get("domain_review_timestamp")
    ) for r in domain_required)
    reviewed = sum(r.get("review_status") not in {"", "draft"} for r in rows)
    def rate(numerator: int, denominator: int) -> float:
        return round(100 * numerator / denominator, 2) if denominator else 100.0
    languages = []
    for row in rows:
        languages.append(
            row.get("language")
            or ("Nigerian Pidgin" if row.get("category") == "nigerian_pidgin" else "Nigerian English")
        )
    unresolved = sum(
        finding.get("severity") == "critical" and not finding.get("resolved", False)
        for assessment in assessments_list for finding in assessment.get("findings", [])
    )
    scorecard = {
        "release_version": release_version,
        "release_status": "immutable_release",
        "record_count": total,
        "eligible_training_count": sum(d.eligible for d in decision_rows),
        "excluded_count": sum(not d.eligible for d in decision_rows),
        "approved_count": statuses["approved"],
        "draft_count": statuses["draft"],
        "rejected_count": statuses["rejected"],
        "superseded_count": statuses["superseded"],
        "technical_review_completion_rate": rate(technical, total),
        "domain_review_completion_rate": rate(domain_done, len(domain_required)),
        "human_review_completion_rate": rate(reviewed, total),
        "provenance_coverage": rate(sum(bool(r.get("source")) for r in rows), total),
        "license_coverage": rate(sum(bool(r.get("license")) for r in rows), total),
        "integrity_pass_rate": rate(sum(
            bool(r.get("example_sha256")) for r in rows
        ), total),
        "average_quality_score": round(statistics.mean(scores), 2) if scores else None,
        "median_quality_score": statistics.median(scores) if scores else None,
        "minimum_quality_score": min(scores) if scores else None,
        "maximum_quality_score": max(scores) if scores else None,
        "category_distribution": _distribution(rows, "category"),
        "risk_distribution": _distribution(rows, "risk_level"),
        "language_distribution": dict(sorted(Counter(languages).items())),
        "source_distribution": _distribution(rows, "source"),
        "license_distribution": _distribution(rows, "license"),
        "quality_distribution": dict(sorted(Counter(
            f"{score // 10 * 10}-{min(score // 10 * 10 + 9, 100)}" for score in scores
        ).items())),
        "unresolved_critical_findings": unresolved,
        "duplicate_count": duplicate_count,
        "benchmark_coverage": benchmark_coverage,
        "manifest_sha256": file_sha256(manifest_path),
        "generated_at": generated_at(),
    }
    scorecard["scorecard_sha256"] = canonical_hash(scorecard)
    return scorecard


def public_scorecard(scorecard: dict[str, Any]) -> dict[str, Any]:
    forbidden = {"reviewer", "reviewer_identifier", "review_notes", "evidence_path"}
    return {key: value for key, value in scorecard.items() if key not in forbidden}

"""Write-once downstream summaries after explicit human review actions."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any, Sequence

from src.dataset_management import atomic_create
from src.quality_intelligence import assess_records
from src.release_scorecard import generate_scorecard
from src.review_automation.duplicates import find_duplicate_matches
from src.review_automation.service import utc_now
from src.training_eligibility import assess_eligibility


def _safe_stamp(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("+00:00", "Z")


def _new_run(root: Path, version: str, timestamp: str) -> Path:
    base = root / version
    if not base.exists() or not any(base.iterdir()):
        return base
    candidate = base / f"run-{_safe_stamp(timestamp)}"
    suffix = 1
    while candidate.exists():
        candidate = base / f"run-{_safe_stamp(timestamp)}-{suffix}"
        suffix += 1
    return candidate


def _write_json(path: Path, value: Any) -> None:
    atomic_create(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def refresh_review_outputs(
    records: Sequence[dict[str, Any]],
    version: str,
    *,
    output_root: Path = Path("evaluation/review_refresh"),
    release_root: Path = Path("data/releases"),
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Recalculate advisory quality, eligibility, progress, and a scorecard.

    This function creates reports only. It never builds or publishes a release.
    """
    timestamp = generated_at or utc_now()
    assessments = assess_records(records, assessed_at=timestamp)
    assessment_rows = [asdict(assessment) for assessment in assessments]
    assessment_by_id = {
        assessment["record_id"]: assessment for assessment in assessment_rows
    }
    duplicate_ids = {
        str(record["id"])
        for record in records
        if find_duplicate_matches(record, records)
    }
    decisions = [
        assess_eligibility(
            record,
            version,
            critical_findings=assessment_by_id[str(record["id"])]["findings"],
            duplicate_ids=duplicate_ids,
            now=lambda: timestamp,
        )
        for record in records
    ]
    statuses = Counter(str(record.get("review_status", "draft")) for record in records)
    category_total = Counter(str(record.get("category", "")) for record in records)
    category_reviewed = Counter(
        str(record.get("category", ""))
        for record in records
        if record.get("review_status") != "draft"
    )
    progress = {
        "schema": "gaialab.review-progress.v1",
        "dataset_version": version,
        "generated_at": timestamp,
        "record_count": len(records),
        "status_counts": dict(sorted(statuses.items())),
        "reviewed_count": sum(
            status not in {"draft", "automated_reviewed"}
            for status in (record.get("review_status") for record in records)
        ),
        "training_eligible_count": sum(decision.eligible for decision in decisions),
        "domain_review_backlog": sum(
            record.get("category") in {"banking", "healthcare", "government_services"}
            and not (
                record.get("domain_review_completed")
                or record.get("domain_review_timestamp")
            )
            for record in records
        ),
        "critical_findings": sum(
            finding.get("severity") == "critical"
            for assessment in assessment_rows
            for finding in assessment["findings"]
        ),
        "category_completion": {
            category: {
                "reviewed": category_reviewed[category],
                "total": count,
            }
            for category, count in sorted(category_total.items())
        },
        "release_created": False,
        "release_published": False,
    }
    scores = [assessment["overall_score"] for assessment in assessment_rows]
    quality_summary = {
        "schema": "gaialab.review-quality-summary.v1",
        "dataset_version": version,
        "generated_at": timestamp,
        "record_count": len(assessment_rows),
        "average_quality_score": (
            round(sum(scores) / len(scores), 4) if scores else None
        ),
        "minimum_quality_score": min(scores) if scores else None,
        "maximum_quality_score": max(scores) if scores else None,
        "recommended_actions": dict(sorted(Counter(
            assessment["recommended_action"] for assessment in assessment_rows
        ).items())),
        "human_approval_assigned": False,
    }
    output = _new_run(output_root, version, timestamp)
    quality_path = output / "quality_assessments.jsonl"
    eligibility_path = output / "eligibility_decisions.jsonl"
    atomic_create(
        quality_path,
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in assessment_rows
        ),
    )
    atomic_create(
        eligibility_path,
        "".join(
            json.dumps(asdict(decision), ensure_ascii=False, sort_keys=True) + "\n"
            for decision in decisions
        ),
    )
    quality_summary_path = output / "quality_summary.json"
    progress_path = output / "review_progress.json"
    _write_json(quality_summary_path, quality_summary)
    _write_json(progress_path, progress)

    outputs = {
        "quality_assessments": quality_path,
        "quality_summary": quality_summary_path,
        "eligibility_decisions": eligibility_path,
        "review_progress": progress_path,
    }
    release = release_root / version
    manifest = release / "dataset_manifest.json"
    if manifest.is_file():
        duplicates_path = release / "semantic_duplicates.json"
        duplicate_count = (
            len(json.loads(duplicates_path.read_text(encoding="utf-8")))
            if duplicates_path.is_file()
            else len(duplicate_ids)
        )
        scorecard = generate_scorecard(
            version,
            records,
            manifest,
            decisions=decisions,
            assessments=assessment_rows,
            duplicate_count=duplicate_count,
            generated_at=lambda: timestamp,
        )
        scorecard_path = output / "scorecard.json"
        _write_json(scorecard_path, scorecard)
        outputs["scorecard"] = scorecard_path
    return {
        "dataset_version": version,
        "generated_at": timestamp,
        "record_count": len(records),
        "official_status_changes": 0,
        "release_created": False,
        "release_published": False,
        "outputs": outputs,
    }

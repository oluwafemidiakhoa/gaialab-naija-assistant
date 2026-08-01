from __future__ import annotations

import json
from pathlib import Path

from src.dataset_management import import_version, review_state
from src.review_automation.analyzer import ReviewAnalyzer
from src.review_automation.audit import append_audit_event, automated_event
from src.review_automation.bulk import (
    CONFIRMATION_PHRASE,
    build_bulk_preview,
    execute_bulk_review,
)
from src.review_automation.config import load_review_config
from src.review_automation.refresh import refresh_review_outputs
from src.review_automation.service import load_latest_assessments


VERSION = "vrefresh-link"
REVIEWER = "technical-reviewer-01"


def record(index: int, *, duplicate: bool = False) -> dict:
    prompt = (
        "Write a polite follow-up asking our Enugu supplier for a confirmed delivery update."
        if duplicate or index == 0
        else "Write a concise reminder for an unpaid Lagos invoice without adding a penalty."
    )
    response = (
        "Good day. Please confirm the current delivery status for our Enugu order. Thank you."
        if duplicate or index == 0
        else "Good day. This is a reminder that the Lagos invoice remains unpaid. Please share an update."
    )
    return {
        "id": f"vrefresh-{index:03d}",
        "category": "small_business",
        "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Be concise, factual, and safe."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": "draft",
    }


def environment(tmp_path: Path, rows: list[dict]):
    source = tmp_path / "source.jsonl"
    source.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    import_version(source, registry, VERSION)
    current = review_state(registry, VERSION)
    analyzer = ReviewAnalyzer(load_review_config())
    recommendations = [
        analyzer.analyze(
            row,
            records=current,
            generated_at="2026-08-01T10:00:00+00:00",
        )
        for row in current
    ]
    audit_root = tmp_path / "audit"
    for recommendation in recommendations:
        append_audit_event(audit_root, automated_event(recommendation))
    return registry, audit_root, [item.to_dict() for item in recommendations]


def preview(
    records: list[dict],
    recommendations: list[dict],
    assessments: list[dict],
    audit_root: Path,
    action: str,
):
    return build_bulk_preview(
        records,
        VERSION,
        load_review_config(),
        category="small_business",
        reviewer_id=REVIEWER,
        reviewer_role="technical_reviewer",
        action=action,
        decision_note="I reviewed each selected record and its current governed evidence.",
        assessments=assessments,
        recommendations=recommendations,
        audit_root=audit_root,
    )


def execute(
    value,
    registry: Path,
    audit_root: Path,
    recommendations: list[dict],
    assessments: list[dict],
):
    return execute_bulk_review(
        value,
        load_review_config(),
        registry_dir=registry,
        releases_dir=registry.parent / "releases",
        audit_root=audit_root,
        recommendations=recommendations,
        assessments=assessments,
        confirmation=CONFIRMATION_PHRASE,
        authenticated_reviewer_id=REVIEWER,
        dry_run=False,
    )


def acknowledge(registry: Path, audit_root: Path, recommendations: list[dict]):
    records = review_state(registry, VERSION)
    acknowledgement = preview(records, recommendations, [], audit_root, "acknowledge-analysis")
    assert acknowledgement.allowed_count == len(records)
    execute(acknowledgement, registry, audit_root, recommendations, [])
    current = review_state(registry, VERSION)
    assert all(row["review_status"] == "automated_reviewed" for row in current)
    return current


def test_draft_to_refresh_to_technical_reviewed(tmp_path: Path):
    registry, audit_root, recommendations = environment(tmp_path, [record(0)])
    automated = acknowledge(registry, audit_root, recommendations)
    refresh_root = tmp_path / "review_refresh"
    refresh_review_outputs(
        automated,
        VERSION,
        output_root=refresh_root,
        release_root=tmp_path / "releases",
        generated_at="2026-08-01T11:00:00+00:00",
    )
    assessments = load_latest_assessments(
        VERSION,
        quality_root=tmp_path / "quality",
        refresh_root=refresh_root,
    )
    technical = preview(automated, recommendations, assessments, audit_root, "technical-review")
    assert technical.allowed_count == 1
    assert "current_quality_assessment_missing" not in technical.items[0].blocking_reasons
    result = execute(technical, registry, audit_root, recommendations, assessments)
    assert result["records_written"] == 1
    assert review_state(registry, VERSION)[0]["review_status"] == "technical_reviewed"


def test_duplicate_blocked_records_remain_blocked_after_refresh(tmp_path: Path):
    registry, audit_root, recommendations = environment(
        tmp_path, [record(0), record(1, duplicate=True)]
    )
    automated = acknowledge(registry, audit_root, recommendations)
    refresh_root = tmp_path / "review_refresh"
    refresh_review_outputs(
        automated,
        VERSION,
        output_root=refresh_root,
        release_root=tmp_path / "releases",
        generated_at="2026-08-01T11:00:00+00:00",
    )
    assessments = load_latest_assessments(
        VERSION,
        quality_root=tmp_path / "quality",
        refresh_root=refresh_root,
    )
    technical = preview(automated, recommendations, assessments, audit_root, "technical-review")
    assert technical.allowed_count == 0
    assert all(
        "unresolved_duplicate_finding" in item.blocking_reasons
        for item in technical.items
    )
    assert all(
        row["review_status"] == "automated_reviewed"
        for row in review_state(registry, VERSION)
    )


def test_newer_refresh_assessment_is_loaded_and_current_record_is_allowed(tmp_path: Path):
    registry, audit_root, recommendations = environment(tmp_path, [record(0)])
    automated = acknowledge(registry, audit_root, recommendations)
    quality = tmp_path / "quality" / VERSION
    quality.mkdir(parents=True)
    (quality / "quality_assessments.jsonl").write_text(
        json.dumps({
            "record_id": automated[0]["id"],
            "record_sha256": "0" * 64,
            "assessed_at": "2026-07-31T10:00:00+00:00",
            "overall_score": 100,
            "findings": [],
        }) + "\n",
        encoding="utf-8",
    )
    refresh_root = tmp_path / "review_refresh"
    refresh_review_outputs(
        automated,
        VERSION,
        output_root=refresh_root,
        release_root=tmp_path / "releases",
        generated_at="2026-08-01T11:00:00+00:00",
    )
    assessments = load_latest_assessments(
        VERSION,
        quality_root=tmp_path / "quality",
        refresh_root=refresh_root,
    )
    assert assessments[0]["record_sha256"] == automated[0]["example_sha256"]
    technical = preview(automated, recommendations, assessments, audit_root, "technical-review")
    assert technical.allowed_count == 1
    assert technical.items[0].blocking_reasons == ()

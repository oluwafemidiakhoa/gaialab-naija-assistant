"""Read-only release and publication state derived from explicit evidence."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from src.dataset_management import read_jsonl, snapshot_path
from src.review_automation.service import (
    load_latest_assessments,
    load_version_records,
)
from src.training_eligibility import assess_eligibility


PUBLICATION_EVENTS = {
    "release_verified",
    "publication_approved",
    "dataset_published",
}


def _publication_events(path: Path, version: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [
        event for event in read_jsonl(path)
        if event.get("version") == version
        and event.get("event") in PUBLICATION_EVENTS
    ]


def release_status(
    version: str,
    *,
    registry_dir: Path = Path("data/registry"),
    releases_dir: Path = Path("data/releases"),
    candidate_root: Path = Path("data/release_candidates"),
    publication_registry: Path = Path(
        "data/governance/publication_events.jsonl"
    ),
) -> dict[str, Any]:
    """Report state without inferring publication from a directory name."""
    registry_snapshot = snapshot_path(registry_dir, version)
    local_release = releases_dir / version / f"{version}.jsonl"
    local_data = Path("data") / version
    exists = (
        registry_snapshot.is_file()
        or local_release.is_file()
        or local_data.is_dir()
    )
    candidate_manifest = (
        candidate_root / version / "release_candidate_manifest.json"
    )
    candidate_exists = candidate_manifest.is_file()
    events = _publication_events(publication_registry, version)
    verified = any(event["event"] == "release_verified" for event in events)
    approved = any(event["event"] == "publication_approved" for event in events)
    published = any(event["event"] == "dataset_published" for event in events)
    if published:
        status = "published"
    elif approved:
        status = "approved_for_publication"
    elif verified:
        status = "verified"
    elif candidate_exists:
        status = "release_candidate"
    elif exists:
        status = "under_review"
    else:
        status = "not_created"
    return {
        "version": version,
        "exists_locally": exists,
        "local_dataset_version": exists,
        "release_candidate_exists": candidate_exists,
        "verified": verified,
        "approved_for_publication": approved,
        "published": published,
        "status": status,
        "publication_evidence_count": len(events),
        "publication_inferred_from_folder": False,
    }


def publication_readiness(
    version: str,
    *,
    registry_dir: Path = Path("data/registry"),
    releases_dir: Path = Path("data/releases"),
    candidate_root: Path = Path("data/release_candidates"),
    publication_registry: Path = Path(
        "data/governance/publication_events.jsonl"
    ),
    assessments: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate publication gates without creating or uploading anything."""
    state = release_status(
        version,
        registry_dir=registry_dir,
        releases_dir=releases_dir,
        candidate_root=candidate_root,
        publication_registry=publication_registry,
    )
    if not state["exists_locally"]:
        return {
            **state,
            "record_count": 0,
            "review_completion_percentage": 0.0,
            "approved_count": 0,
            "rejected_count": 0,
            "unresolved_revisions": 0,
            "technical_review_backlog": 0,
            "domain_review_backlog": 0,
            "provenance_completeness_percentage": 0.0,
            "unresolved_critical_findings": 0,
            "training_eligible_count": 0,
            "ready_for_publication": False,
            "blocking_reasons": ["dataset_not_created"],
            "upload_performed": False,
            "git_operation_performed": False,
        }
    records = load_version_records(
        version,
        registry_dir=registry_dir,
        releases_dir=releases_dir,
    )
    assessment_rows = list(
        load_latest_assessments(version)
        if assessments is None else assessments
    )
    status_counts = Counter(
        str(record.get("review_status", "draft")) for record in records
    )
    finalized = sum(
        status_counts[status] for status in ("approved", "rejected", "superseded")
    )
    technical_backlog = sum(
        not (
            record.get("technical_review_completed")
            or record.get("review_status")
            in {"technical_reviewed", "domain_reviewed", "approved"}
        )
        for record in records
    )
    domain_backlog = sum(
        record.get("category") in {"banking", "healthcare", "government_services"}
        and not (
            record.get("domain_review_completed")
            or record.get("domain_review_timestamp")
        )
        for record in records
    )
    provenance_complete = sum(
        bool(str(record.get("source", "")).strip())
        and str(record.get("source", "")).casefold()
        not in {"unknown", "provenance_unknown"}
        and bool(str(record.get("license", "")).strip())
        for record in records
    )
    critical = sum(
        finding.get("severity") == "critical"
        and not finding.get("resolved", False)
        for assessment in assessment_rows
        for finding in assessment.get("findings", [])
    )
    decisions = [
        assess_eligibility(
            record,
            version,
            critical_findings=next(
                (
                    assessment.get("findings", [])
                    for assessment in assessment_rows
                    if assessment.get("record_id") == record.get("id")
                ),
                (),
            ),
        )
        for record in records
    ]
    blockers: list[str] = []
    if finalized != len(records):
        blockers.append("human_review_incomplete")
    if technical_backlog:
        blockers.append("technical_review_backlog")
    if domain_backlog:
        blockers.append("domain_review_backlog")
    if provenance_complete != len(records):
        blockers.append("provenance_incomplete")
    if critical:
        blockers.append("unresolved_critical_findings")
    if status_counts["needs_revision"]:
        blockers.append("unresolved_revisions")
    if not state["release_candidate_exists"]:
        blockers.append("release_candidate_missing")
    if not state["verified"]:
        blockers.append("release_not_verified")
    if not state["approved_for_publication"]:
        blockers.append("publication_not_approved")
    return {
        **state,
        "record_count": len(records),
        "review_completion_percentage": (
            round(100 * finalized / len(records), 2) if records else 0.0
        ),
        "approved_count": status_counts["approved"],
        "rejected_count": status_counts["rejected"],
        "unresolved_revisions": status_counts["needs_revision"],
        "technical_review_backlog": technical_backlog,
        "domain_review_backlog": domain_backlog,
        "provenance_completeness_percentage": (
            round(100 * provenance_complete / len(records), 2)
            if records else 0.0
        ),
        "unresolved_critical_findings": critical,
        "training_eligible_count": sum(
            decision.eligible for decision in decisions
        ),
        "ready_for_publication": not blockers,
        "blocking_reasons": blockers,
        "upload_performed": False,
        "git_operation_performed": False,
    }

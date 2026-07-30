"""Preview-first, human-gated bulk review over append-only registry state."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

from src.dataset_management import (
    DatasetManagementError,
    example_sha256,
    read_jsonl,
    review_state,
)
from src.review_automation.analyzer import SAFETY_CHECKS
from src.review_automation.audit import audit_path
from src.review_automation.config import ReviewAutomationConfig
from src.review_automation.models import (
    AdvisoryRecommendation,
    ReviewAutomationModelError,
    canonical_sha256,
)
from src.review_automation.revisions import (
    DECISION_TRANSITIONS,
    apply_human_decision,
)
from src.review_automation.service import load_version_records, utc_now
from src.review_workflow import REVIEWER_ROLES, ROLE_FOR_STATE, TRANSITIONS
from src.training_eligibility import ALLOWED_LICENSES, assess_eligibility


CONFIRMATION_PHRASE = "I HAVE REVIEWED THESE RECORDS"
BULK_ACTIONS = {
    "acknowledge-analysis": "acknowledge_analysis",
    "technical-review": "technical_review",
    "request-revision": "request_revision",
    "reject": "reject",
    "escalate": "escalate",
    "approve": "approve",
}
FINDING_GATED_ACTIONS = {"technical_review", "approve"}


@dataclass(frozen=True)
class BulkReviewItem:
    """One deterministic selection decision in a bulk preview."""

    record_id: str
    record_revision: int
    record_sha256: str
    category: str
    risk_level: str
    review_status: str
    recommendation: str
    recommendation_hash: str
    quality_score: int
    unresolved_findings: tuple[str, ...]
    technical_review_required: bool
    domain_review_required: bool
    eligibility_blockers: tuple[str, ...]
    training_eligible: bool
    allowed: bool
    blocking_reasons: tuple[str, ...]


@dataclass(frozen=True)
class BulkReviewPreview:
    """Stable preview that must be confirmed before any append-only writes."""

    dataset_version: str
    category: str
    reviewer_id: str
    reviewer_role: str
    action: str
    internal_action: str
    decision_note: str
    limit: int
    escalation_target: str | None
    selected_count: int
    allowed_count: int
    blocked_count: int
    items: tuple[BulkReviewItem, ...]
    preview_sha256: str
    batch_operation_id: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["records_allowed"] = [
            item.record_id for item in self.items if item.allowed
        ]
        value["records_blocked"] = [
            item.record_id for item in self.items if not item.allowed
        ]
        value["dry_run_default"] = True
        value["human_confirmation_required"] = CONFIRMATION_PHRASE
        value["ai_recommendations_are_advisory"] = True
        return value


def _assessment_map(
    assessments: Iterable[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {
        str(value.get("record_id")): value
        for value in assessments
        if value.get("record_id")
    }


def _recommendation_map(
    recommendations: Iterable[dict[str, Any]],
    records: Iterable[dict[str, Any]],
    version: str,
) -> dict[str, AdvisoryRecommendation]:
    current = {str(record.get("id")): record for record in records}
    result: dict[str, AdvisoryRecommendation] = {}
    for value in recommendations:
        record = current.get(str(value.get("record_id")))
        if record is None:
            continue
        if (
            value.get("dataset_version") != version
            or value.get("record_revision") != record.get("revision")
            or value.get("input_record_sha256") != record.get("example_sha256")
        ):
            continue
        try:
            recommendation = AdvisoryRecommendation.from_dict(value)
        except ReviewAutomationModelError:
            continue
        prior = result.get(recommendation.record_id)
        if (
            prior is None
            or recommendation.generation_timestamp > prior.generation_timestamp
        ):
            result[recommendation.record_id] = recommendation
    return result


def _audited_recommendation_hashes(audit_root: Path, version: str) -> set[str]:
    path = audit_path(audit_root, version, human=False)
    if not path.is_file():
        return set()
    return {
        str(row.get("recommendation_hash"))
        for row in read_jsonl(path)
        if row.get("recommendation_hash")
    }


def _unresolved_findings(
    assessment: dict[str, Any],
    recommendation: AdvisoryRecommendation | None,
) -> tuple[str, ...]:
    values: list[str] = []
    for finding in assessment.get("findings", []):
        if not isinstance(finding, dict) or finding.get("resolved", False):
            continue
        severity = str(finding.get("severity", "unknown"))
        check = str(finding.get("check", "unspecified"))
        message = str(finding.get("message", "")).strip()
        values.append(f"{severity}:{check}:{message or 'unresolved finding'}")
    if recommendation is not None:
        advisory_groups = (
            ("safety", recommendation.safety_findings),
            ("factuality", recommendation.factuality_concerns),
            ("unsupported_claim", recommendation.unsupported_claim_indicators),
            ("high_risk", recommendation.high_risk_domain_indicators),
        )
        for group, findings in advisory_groups:
            values.extend(f"advisory:{group}:{finding}" for finding in findings)
        values.extend(
            "duplicate:"
            f"{match.match_type}:{match.matched_record_id}:{match.similarity:.4f}"
            for match in recommendation.duplicate_matches
        )
    return tuple(dict.fromkeys(values))


def _finding_flags(
    assessment: dict[str, Any],
    recommendation: AdvisoryRecommendation | None,
) -> dict[str, bool]:
    findings = [
        finding
        for finding in assessment.get("findings", [])
        if isinstance(finding, dict) and not finding.get("resolved", False)
    ]
    checks = {str(finding.get("check", "")) for finding in findings}
    return {
        "critical": any(
            finding.get("severity") == "critical" for finding in findings
        ),
        "high": any(finding.get("severity") == "high" for finding in findings),
        "safety": bool(
            checks & SAFETY_CHECKS
            or (
                recommendation is not None
                and (
                    recommendation.safety_findings
                    or recommendation.high_risk_domain_indicators
                )
            )
        ),
        "duplicate": bool(
            any("duplicate" in check for check in checks)
            or (
                recommendation is not None
                and recommendation.duplicate_matches
            )
        ),
        "provenance": any(
            "provenance" in check or check.startswith("source_")
            for check in checks
        ),
        "licensing": any("licen" in check for check in checks),
    }


def _blocking_reasons(
    record: dict[str, Any],
    *,
    action: str,
    reviewer_role: str,
    recommendation: AdvisoryRecommendation | None,
    recommendation_is_audited: bool,
    assessment: dict[str, Any],
    config: ReviewAutomationConfig,
    dataset_version: str,
) -> tuple[str, ...]:
    reasons: list[str] = []
    status = str(record.get("review_status", "draft"))
    new_status = DECISION_TRANSITIONS[action]
    if new_status not in TRANSITIONS.get(status, set()):
        reasons.append(f"invalid_transition:{status}->{new_status}")
    permitted_roles = ROLE_FOR_STATE.get(new_status)
    if permitted_roles and reviewer_role not in permitted_roles:
        reasons.append(f"role_not_permitted:{reviewer_role}->{new_status}")
    if str(record.get("risk_level", "")) != "low":
        reasons.append("bulk_requires_low_risk")
    if str(record.get("source", "")).strip().casefold() != "synthetic":
        reasons.append("bulk_requires_synthetic_source")
    if record.get("dataset_version") != dataset_version:
        reasons.append("wrong_dataset_version")
    if str(record.get("example_sha256", "")) != example_sha256(record):
        reasons.append("content_hash_mismatch")
    license_name = str(record.get("license", "")).strip()
    if not license_name:
        reasons.append("license_missing")
    elif license_name not in ALLOWED_LICENSES:
        reasons.append("license_not_allowed")
    if recommendation is None:
        reasons.append("current_advisory_recommendation_missing")
    elif not recommendation_is_audited:
        reasons.append("advisory_recommendation_not_audited")

    flags = _finding_flags(assessment, recommendation)
    if action in FINDING_GATED_ACTIONS:
        if assessment.get("record_sha256") != record.get("example_sha256"):
            reasons.append("current_quality_assessment_missing")
        if flags["critical"]:
            reasons.append("unresolved_critical_finding")
        if flags["safety"]:
            reasons.append("unresolved_safety_finding")
        if flags["duplicate"]:
            reasons.append("unresolved_duplicate_finding")
        if flags["provenance"]:
            reasons.append("unresolved_provenance_finding")
        if flags["licensing"]:
            reasons.append("unresolved_licensing_finding")
    if action == "approve":
        technical_complete = bool(
            record.get("technical_review_completed")
            or status in {"technical_reviewed", "domain_reviewed", "approved"}
        )
        if not technical_complete:
            reasons.append("technical_review_incomplete")
        domain_required = bool(
            str(record.get("category", "")) in config.domain_review_categories
            or (
                recommendation is not None
                and recommendation.domain_review_required
            )
        )
        if domain_required:
            reasons.append("domain_review_record_cannot_be_bulk_approved")
        if flags["high"]:
            reasons.append("unresolved_high_finding")
        if recommendation is not None and recommendation.quality_score < (
            config.minimum_quality_score
        ):
            reasons.append("quality_below_minimum")
    return tuple(dict.fromkeys(reasons))


def _preview_hash_payload(
    *,
    version: str,
    category: str,
    reviewer_id: str,
    reviewer_role: str,
    action: str,
    note: str,
    limit: int,
    escalation_target: str | None,
    items: tuple[BulkReviewItem, ...],
) -> dict[str, Any]:
    return {
        "dataset_version": version,
        "category": category,
        "reviewer_id": reviewer_id,
        "reviewer_role": reviewer_role,
        "action": action,
        "decision_note_sha256": hashlib.sha256(note.encode("utf-8")).hexdigest(),
        "limit": limit,
        "escalation_target": escalation_target,
        "items": [asdict(item) for item in items],
    }


def build_bulk_preview(
    records: Iterable[dict[str, Any]],
    version: str,
    config: ReviewAutomationConfig,
    *,
    category: str,
    reviewer_id: str,
    reviewer_role: str,
    action: str,
    decision_note: str,
    limit: int = 20,
    escalation_target: str | None = None,
    assessments: Iterable[dict[str, Any]] = (),
    recommendations: Iterable[dict[str, Any]] = (),
    audit_root: Path = Path("evaluation/review_audit"),
) -> BulkReviewPreview:
    """Build a read-only deterministic batch preview with explicit blockers."""
    if action not in BULK_ACTIONS:
        raise DatasetManagementError("unsupported bulk human-review action")
    if reviewer_role not in REVIEWER_ROLES:
        raise DatasetManagementError("invalid reviewer role")
    if not reviewer_id.strip():
        raise DatasetManagementError("reviewer ID is required")
    if not category.strip():
        raise DatasetManagementError("category is required")
    if not decision_note.strip():
        raise DatasetManagementError("a non-empty decision note is required")
    if not 1 <= limit <= 500:
        raise DatasetManagementError("limit must be from 1 to 500")
    if action == "escalate" and escalation_target not in {
        "technical",
        "domain",
        "safety",
        "provenance",
    }:
        raise DatasetManagementError(
            "escalation target must be technical, domain, safety, or provenance"
        )
    if action != "escalate" and escalation_target is not None:
        raise DatasetManagementError(
            "escalation target is only valid for the escalate action"
        )

    rows = sorted(
        (
            record
            for record in records
            if str(record.get("category", "")) == category
        ),
        key=lambda record: str(record.get("id", "")),
    )[:limit]
    assessment_by_id = _assessment_map(assessments)
    recommendation_by_id = _recommendation_map(recommendations, rows, version)
    audited_hashes = _audited_recommendation_hashes(audit_root, version)
    internal_action = BULK_ACTIONS[action]
    items: list[BulkReviewItem] = []
    for record in rows:
        record_id = str(record.get("id", ""))
        assessment = assessment_by_id.get(record_id, {})
        recommendation = recommendation_by_id.get(record_id)
        duplicate_ids = (
            {record_id}
            if _finding_flags(assessment, recommendation)["duplicate"]
            else set()
        )
        eligibility = assess_eligibility(
            record,
            version,
            critical_findings=assessment.get("findings", ()),
            duplicate_ids=duplicate_ids,
        )
        blockers = _blocking_reasons(
            record,
            action=internal_action,
            reviewer_role=reviewer_role,
            recommendation=recommendation,
            recommendation_is_audited=bool(
                recommendation
                and recommendation.recommendation_hash in audited_hashes
            ),
            assessment=assessment,
            config=config,
            dataset_version=version,
        )
        status = str(record.get("review_status", "draft"))
        domain_required = bool(
            record.get("category") in config.domain_review_categories
            and status not in {"domain_reviewed", "approved"}
        )
        items.append(BulkReviewItem(
            record_id=record_id,
            record_revision=int(record.get("revision", 1)),
            record_sha256=str(record.get("example_sha256", "")),
            category=str(record.get("category", "")),
            risk_level=str(record.get("risk_level", "")),
            review_status=status,
            recommendation=(
                recommendation.recommendation.value
                if recommendation is not None
                else "missing"
            ),
            recommendation_hash=(
                recommendation.recommendation_hash
                if recommendation is not None
                else ""
            ),
            quality_score=int(
                assessment.get(
                    "overall_score",
                    recommendation.quality_score
                    if recommendation is not None
                    else 0,
                )
            ),
            unresolved_findings=_unresolved_findings(
                assessment, recommendation
            ),
            technical_review_required=status not in {
                "technical_reviewed",
                "domain_reviewed",
                "approved",
            },
            domain_review_required=domain_required,
            eligibility_blockers=tuple(eligibility.reasons),
            training_eligible=eligibility.eligible,
            allowed=not blockers,
            blocking_reasons=blockers,
        ))
    immutable_items = tuple(items)
    payload = _preview_hash_payload(
        version=version,
        category=category,
        reviewer_id=reviewer_id.strip(),
        reviewer_role=reviewer_role,
        action=action,
        note=decision_note.strip(),
        limit=limit,
        escalation_target=escalation_target,
        items=immutable_items,
    )
    preview_sha256 = canonical_sha256(payload)
    operation_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"gaialab-bulk-review:{preview_sha256}",
    ))
    allowed_count = sum(item.allowed for item in immutable_items)
    return BulkReviewPreview(
        dataset_version=version,
        category=category,
        reviewer_id=reviewer_id.strip(),
        reviewer_role=reviewer_role,
        action=action,
        internal_action=internal_action,
        decision_note=decision_note.strip(),
        limit=limit,
        escalation_target=escalation_target,
        selected_count=len(immutable_items),
        allowed_count=allowed_count,
        blocked_count=len(immutable_items) - allowed_count,
        items=immutable_items,
        preview_sha256=preview_sha256,
        batch_operation_id=operation_id,
    )


def execute_bulk_review(
    preview: BulkReviewPreview,
    config: ReviewAutomationConfig,
    *,
    registry_dir: Path = Path("data/registry"),
    releases_dir: Path = Path("data/releases"),
    audit_root: Path = Path("evaluation/review_audit"),
    assessments: Iterable[dict[str, Any]] = (),
    recommendations: Iterable[dict[str, Any]] = (),
    confirmation: str | None = None,
    authenticated_reviewer_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Revalidate and append one governed human event per allowed record."""
    if dry_run:
        return {
            "batch_operation_id": preview.batch_operation_id,
            "dry_run": True,
            "write_performed": False,
            "records_written": 0,
            "records_blocked": preview.blocked_count,
            "results": [],
        }
    if confirmation != CONFIRMATION_PHRASE:
        raise DatasetManagementError(
            f'real bulk review requires --confirm "{CONFIRMATION_PHRASE}"'
        )
    if authenticated_reviewer_id != preview.reviewer_id:
        raise DatasetManagementError(
            "authenticated reviewer identity does not match --reviewer-id"
        )
    current_records = load_version_records(
        preview.dataset_version,
        registry_dir=registry_dir,
        releases_dir=releases_dir,
    )
    current_preview = build_bulk_preview(
        current_records,
        preview.dataset_version,
        config,
        category=preview.category,
        reviewer_id=preview.reviewer_id,
        reviewer_role=preview.reviewer_role,
        action=preview.action,
        decision_note=preview.decision_note,
        limit=preview.limit,
        escalation_target=preview.escalation_target,
        assessments=assessments,
        recommendations=recommendations,
        audit_root=audit_root,
    )
    if current_preview.preview_sha256 != preview.preview_sha256:
        raise DatasetManagementError(
            "bulk preview is stale; generate and inspect a new preview"
        )
    recommendation_by_id = _recommendation_map(
        recommendations,
        current_records,
        preview.dataset_version,
    )
    timestamp = utc_now()
    results: list[dict[str, Any]] = []
    for item in current_preview.items:
        if not item.allowed:
            continue
        recommendation = recommendation_by_id[item.record_id]
        result = apply_human_decision(
            registry_dir,
            audit_root,
            preview.dataset_version,
            item.record_id,
            preview.internal_action,
            preview.reviewer_id,
            preview.reviewer_role,
            recommendation=recommendation,
            decision_note=preview.decision_note,
            confirm_approval=preview.internal_action == "approve",
            confirm_rejection=preview.internal_action == "reject",
            escalation_target=preview.escalation_target,
            batch_operation_id=preview.batch_operation_id,
            now=lambda: timestamp,
        )
        results.append({
            "record_id": item.record_id,
            "previous_status": result["prior_status"],
            "new_status": result["new_status"],
            "record_revision": item.record_revision,
            "record_sha256": item.record_sha256,
            "recommendation_hash": item.recommendation_hash,
            "event_sha256": result["human_audit_sha256"],
            "batch_operation_id": preview.batch_operation_id,
        })

    state = {
        str(record.get("id")): record
        for record in review_state(registry_dir, preview.dataset_version)
    }
    assessment_by_id = _assessment_map(assessments)
    eligibility_after = {
        result["record_id"]: assess_eligibility(
            state[result["record_id"]],
            preview.dataset_version,
            critical_findings=assessment_by_id.get(
                result["record_id"], {}
            ).get("findings", ()),
        ).eligible
        for result in results
    }
    return {
        "batch_operation_id": preview.batch_operation_id,
        "dry_run": False,
        "write_performed": bool(results),
        "records_written": len(results),
        "records_blocked": current_preview.blocked_count,
        "results": results,
        "training_eligibility_after": eligibility_after,
        "upload_performed": False,
        "publication_performed": False,
        "training_performed": False,
        "git_operation_performed": False,
    }

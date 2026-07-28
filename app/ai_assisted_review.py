"""Streamlit dashboard for advisory analysis and explicit human review."""

from __future__ import annotations

import os
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src.dataset_management import DatasetManagementError, list_versions  # noqa: E402
from src.review_automation.audit import audit_history  # noqa: E402
from src.review_automation.config import load_review_config  # noqa: E402
from src.review_automation.models import (  # noqa: E402
    AdvisoryRecommendation,
    ReviewAutomationModelError,
)
from src.review_automation.guided import approval_blockers  # noqa: E402
from src.review_automation.queue import QueueFilters, build_queue  # noqa: E402
from src.review_automation.refresh import refresh_review_outputs  # noqa: E402
from src.review_automation.revisions import (  # noqa: E402
    apply_human_decision,
    apply_revision_action,
)
from src.review_automation.service import (  # noqa: E402
    analyze_records,
    load_latest_assessments,
    load_latest_recommendations,
    load_version_records,
    write_analysis_run,
)
from src.training_eligibility import assess_eligibility  # noqa: E402


REGISTRY_DIR = Path(os.getenv("GAIALAB_DATASET_REGISTRY", "data/registry"))
RELEASES_DIR = Path(os.getenv("GAIALAB_DATASET_RELEASES", "data/releases"))
AUTOMATED_DIR = Path(
    os.getenv("GAIALAB_AUTOMATED_REVIEWS", "evaluation/automated_reviews")
)
AUDIT_DIR = Path(os.getenv("GAIALAB_REVIEW_AUDIT", "evaluation/review_audit"))
REFRESH_DIR = Path(
    os.getenv("GAIALAB_REVIEW_REFRESH", "evaluation/review_refresh")
)


def available_decisions(
    status: str,
    *,
    domain_review_required: bool,
) -> tuple[str, ...]:
    """Return only transitions supported by the existing governed workflow."""
    if status == "draft":
        return ("acknowledge_analysis", "reject")
    if status == "automated_reviewed":
        return (
            "technical_review",
            "request_revision",
            "reject",
            "escalate",
        )
    if status == "technical_reviewed":
        approval = ("domain_review",) if domain_review_required else ("approve",)
        return approval + ("request_revision", "reject", "escalate")
    if status == "domain_reviewed":
        return ("approve", "request_revision", "reject", "escalate")
    return ()


def current_recommendation(
    rows: Iterable[dict[str, Any]],
    record: dict[str, Any],
) -> AdvisoryRecommendation | None:
    """Return the newest valid recommendation for the current immutable content."""
    matches: list[AdvisoryRecommendation] = []
    for row in rows:
        if (
            row.get("record_id") == record.get("id")
            and row.get("record_revision") == record.get("revision")
            and row.get("input_record_sha256") == record.get("example_sha256")
        ):
            try:
                matches.append(AdvisoryRecommendation.from_dict(row))
            except ReviewAutomationModelError:
                continue
    return max(matches, key=lambda item: item.generation_timestamp, default=None)


def dataset_summary(
    records: list[dict[str, Any]],
    assessments: Iterable[dict[str, Any]],
    version: str,
) -> dict[str, Any]:
    """Build the non-sensitive dashboard summary."""
    assessment_rows = list(assessments)
    statuses = Counter(str(record.get("review_status", "draft")) for record in records)
    scores = [
        int(row["overall_score"])
        for row in assessment_rows
        if row.get("overall_score") is not None
    ]
    return {
        "total": len(records),
        "draft": statuses["draft"],
        "under_review": sum(
            statuses[name]
            for name in (
                "automated_reviewed",
                "technical_reviewed",
                "domain_reviewed",
            )
        ),
        "approved": statuses["approved"],
        "needs_revision": statuses["needs_revision"],
        "rejected": statuses["rejected"],
        "training_eligible": sum(
            assess_eligibility(record, version).eligible for record in records
        ),
        "critical_findings": sum(
            finding.get("severity") == "critical"
            for row in assessment_rows
            for finding in row.get("findings", [])
        ),
        "high_risk_findings": sum(
            finding.get("severity") == "high"
            for row in assessment_rows
            for finding in row.get("findings", [])
        ),
        "average_quality_score": (
            round(sum(scores) / len(scores), 2) if scores else None
        ),
    }


def _render_summary(summary: dict[str, Any]) -> None:
    columns = st.columns(5)
    columns[0].metric("Total", summary["total"])
    columns[1].metric("Draft", summary["draft"])
    columns[2].metric("Under review", summary["under_review"])
    columns[3].metric("Approved", summary["approved"])
    columns[4].metric("Needs revision", summary["needs_revision"])
    columns = st.columns(5)
    columns[0].metric("Rejected", summary["rejected"])
    columns[1].metric("Training eligible", summary["training_eligible"])
    columns[2].metric("Critical findings", summary["critical_findings"])
    columns[3].metric("High findings", summary["high_risk_findings"])
    columns[4].metric(
        "Average quality",
        summary["average_quality_score"]
        if summary["average_quality_score"] is not None else "Not assessed",
    )


def _recommendation_panel(recommendation: AdvisoryRecommendation) -> None:
    st.subheader("Advisory recommendation")
    st.warning(
        "AI output is advisory only. It cannot approve, reject, or publish this record."
    )
    st.json({
        "recommendation": recommendation.recommendation.value,
        "rationale": recommendation.rationale,
        "confidence": recommendation.confidence_score,
        "quality_score": recommendation.quality_score,
        "technical_review_required": recommendation.technical_review_required,
        "domain_review_required": recommendation.domain_review_required,
        "safety_findings": recommendation.safety_findings,
        "factuality_concerns": recommendation.factuality_concerns,
        "cultural_context_concerns": recommendation.cultural_context_concerns,
        "pidgin_authenticity_concerns": (
            recommendation.pidgin_authenticity_concerns
        ),
        "ambiguity_findings": recommendation.ambiguity_findings,
        "duplicate_matches": [
            {
                "record_id": match.matched_record_id,
                "type": match.match_type,
                "similarity": match.similarity,
                "explanation": match.explanation,
            }
            for match in recommendation.duplicate_matches
        ],
        "recommendation_hash": recommendation.recommendation_hash,
        "prompt_version": recommendation.prompt_version,
        "provider": recommendation.provider,
        "model": recommendation.model_name,
    })


def run(*, configure_page: bool = True) -> None:
    if configure_page:
        st.set_page_config(page_title="AI-Assisted Review", layout="wide")
    st.title("AI-Assisted Review")
    st.caption(
        "Local-first advisory analysis with append-only, explicitly human decisions."
    )
    versions = list_versions(REGISTRY_DIR)
    if not versions:
        st.info("No registered dataset versions are available.")
        return
    version = st.sidebar.selectbox("Dataset version", versions)
    records = load_version_records(
        version,
        registry_dir=REGISTRY_DIR,
        releases_dir=RELEASES_DIR,
    )
    assessments = load_latest_assessments(version)
    recommendation_rows = load_latest_recommendations(
        version,
        reviews_root=AUTOMATED_DIR,
    )
    _render_summary(dataset_summary(records, assessments, version))

    st.header("Review queue")
    categories = st.sidebar.multiselect(
        "Category", sorted({str(record["category"]) for record in records})
    )
    risks = st.sidebar.multiselect(
        "Risk level", sorted({str(record["risk_level"]) for record in records})
    )
    statuses = st.sidebar.multiselect(
        "Review status",
        sorted({str(record["review_status"]) for record in records}),
    )
    include_finalized = st.sidebar.checkbox("Include finalized records")
    domain_only = st.sidebar.checkbox("Domain review required")
    page_size = st.sidebar.slider("Queue page size", 1, 100, 20)
    snapshot = build_queue(
        records,
        version,
        load_review_config(),
        assessments=assessments,
        recommendations=recommendation_rows,
        filters=QueueFilters(
            category=tuple(categories),
            risk_level=tuple(risks),
            review_status=tuple(statuses),
            domain_review_required=True if domain_only else None,
            include_finalized=include_finalized,
        ),
        page=1,
        page_size=page_size,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    st.dataframe([
        {
            "record_id": item.record_id,
            "category": item.category,
            "status": item.review_status,
            "risk": item.effective_risk,
            "quality": item.quality_score,
            "duplicate_likelihood": item.duplicate_likelihood,
            "recommendation": item.recommendation,
            "domain_review": item.domain_review_required,
            "eligible": item.training_eligible,
        }
        for item in snapshot.items
    ], width="stretch")
    if not snapshot.items:
        st.info("No records match the queue filters.")
        return

    by_id = {str(record["id"]): record for record in records}
    selected_id = st.selectbox(
        "Record to review", [item.record_id for item in snapshot.items]
    )
    record = by_id[selected_id]
    recommendation = current_recommendation(recommendation_rows, record)
    if recommendation is None:
        st.info("No stored advisory analysis exists for this record.")
        if st.button("Generate local advisory analysis"):
            values, summary = analyze_records(
                records,
                version,
                load_review_config(),
                record_id=selected_id,
            )
            write_analysis_run(
                values,
                summary,
                AUTOMATED_DIR,
                audit_root=AUDIT_DIR,
            )
            st.success("Stored advisory analysis without changing review status.")
            st.rerun()
        return

    left, right = st.columns([3, 2])
    messages = {
        message["role"]: message["content"] for message in record["messages"]
    }
    with left:
        st.subheader("Original record")
        st.text_area("System", messages["system"], disabled=True)
        st.text_area("User", messages["user"], disabled=True)
        st.text_area("Assistant", messages["assistant"], disabled=True, height=180)
        _recommendation_panel(recommendation)
    with right:
        st.subheader("Audit history")
        st.json(audit_history(AUDIT_DIR, version, selected_id))
        suggestion = recommendation.suggested_revision
        if suggestion is not None:
            st.subheader("Suggested revision")
            suggested_prompt = st.text_area(
                "Suggested user prompt", suggestion.prompt
            )
            suggested_response = st.text_area(
                "Suggested assistant response", suggestion.response, height=180
            )
            st.json({
                "changes": suggestion.changes_summary,
                "reasons": suggestion.reasons,
                "safety_impact": suggestion.safety_impact,
                "factuality_impact": suggestion.factuality_impact,
                "cultural_context_impact": suggestion.cultural_context_impact,
            })

    st.header("Explicit human action")
    reviewer = st.text_input("Reviewer name or stable reviewer ID")
    role = st.selectbox(
        "Reviewer role",
        ["reviewer", "technical_reviewer", "domain_reviewer", "release_manager"],
    )
    note = st.text_area(
        "Decision note",
        help="Required for rejection, escalation, and revision actions.",
    )
    quality_score = st.slider("Human quality score", 0, 100, 70)
    decisions = available_decisions(
        str(record["review_status"]),
        domain_review_required=recommendation.domain_review_required,
    )
    if decisions:
        action = st.selectbox("Decision", decisions)
        if action == "approve":
            blockers = approval_blockers(record, recommendation)
            if blockers:
                st.error("Approval blocked: " + ", ".join(blockers))
        escalation_target = (
            st.selectbox(
                "Escalation target",
                ["technical", "domain", "safety", "provenance"],
            )
            if action == "escalate"
            else None
        )
        confirm = st.checkbox(
            "I confirm this final action is my explicit human decision",
            disabled=action not in {"approve", "reject"},
        )
        if st.button("Record human decision", type="primary"):
            try:
                apply_human_decision(
                    REGISTRY_DIR,
                    AUDIT_DIR,
                    version,
                    selected_id,
                    action,
                    reviewer,
                    role,
                    recommendation=recommendation,
                    decision_note=note,
                    quality_score=quality_score,
                    confirm_approval=confirm if action == "approve" else False,
                    confirm_rejection=confirm if action == "reject" else False,
                    escalation_target=escalation_target,
                )
                refreshed = load_version_records(
                    version,
                    registry_dir=REGISTRY_DIR,
                    releases_dir=RELEASES_DIR,
                )
                refresh_review_outputs(
                    refreshed,
                    version,
                    output_root=REFRESH_DIR,
                    release_root=RELEASES_DIR,
                )
            except (DatasetManagementError, OSError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.success("Human decision appended and summaries refreshed.")
                st.rerun()
    else:
        st.info("No further state transition is available for this record.")

    if recommendation.suggested_revision is not None:
        st.subheader("Human revision controls")
        revision_action = st.radio(
            "Suggestion action",
            [
                "accept_suggested_revision",
                "edit_suggested_revision",
                "discard_suggested_revision",
            ],
            horizontal=True,
        )
        if st.button("Record revision action"):
            try:
                apply_revision_action(
                    REGISTRY_DIR,
                    AUDIT_DIR,
                    version,
                    selected_id,
                    revision_action,
                    reviewer,
                    role,
                    recommendation=recommendation,
                    decision_note=note,
                    edited_prompt=suggested_prompt,
                    edited_response=suggested_response,
                )
                refreshed = load_version_records(
                    version,
                    registry_dir=REGISTRY_DIR,
                    releases_dir=RELEASES_DIR,
                )
                refresh_review_outputs(
                    refreshed,
                    version,
                    output_root=REFRESH_DIR,
                    release_root=RELEASES_DIR,
                )
            except (DatasetManagementError, OSError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.success("Revision action appended; source content was not overwritten.")
                st.rerun()

    st.header("Progress")
    summary = dataset_summary(records, assessments, version)
    st.json({
        "reviewed_today": sum(
            str(record.get("review_date", "")).startswith(
                date.today().isoformat()
            )
            for record in records
        ),
        "remaining_records": (
            summary["draft"] + summary["under_review"] + summary["needs_revision"]
        ),
        "category_completion": {
            category: {
                "reviewed": sum(
                    row["category"] == category and row["review_status"] != "draft"
                    for row in records
                ),
                "total": sum(row["category"] == category for row in records),
            }
            for category in sorted({str(row["category"]) for row in records})
        },
        "domain_review_backlog": sum(
            row["category"] in {"banking", "healthcare", "government_services"}
            and not row.get("domain_review_completed")
            for row in records
        ),
        "training_eligible_count": summary["training_eligible"],
    })


if __name__ == "__main__":
    run()

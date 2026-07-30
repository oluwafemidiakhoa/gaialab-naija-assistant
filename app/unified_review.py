"""Single-page guided human review with deterministic Review Next navigation."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import streamlit as st  # noqa: E402

from ai_assisted_review import current_recommendation  # noqa: E402
from src.dataset_management import (  # noqa: E402
    DatasetManagementError,
    list_versions,
)
from src.review_automation.audit import audit_history  # noqa: E402
from src.review_automation.config import load_review_config  # noqa: E402
from src.review_automation.guided import (  # noqa: E402
    PilotProgress,
    approval_blockers,
    filter_identity,
    pilot_summary,
    queue_summary,
    record_action_and_advance,
    review_next,
)
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
from src.review_workflow import review_history  # noqa: E402


REGISTRY_DIR = Path(os.getenv("GAIALAB_DATASET_REGISTRY", "data/registry"))
RELEASES_DIR = Path(os.getenv("GAIALAB_DATASET_RELEASES", "data/releases"))
AUTOMATED_DIR = Path(
    os.getenv("GAIALAB_AUTOMATED_REVIEWS", "evaluation/automated_reviews")
)
AUDIT_DIR = Path(os.getenv("GAIALAB_REVIEW_AUDIT", "evaluation/review_audit"))
REFRESH_DIR = Path(
    os.getenv("GAIALAB_REVIEW_REFRESH", "evaluation/review_refresh")
)

ACTION_LABELS = {
    "acknowledge_analysis": "Acknowledge Analysis",
    "technical_review": "Complete Technical Review",
    "domain_review": "Complete Domain Review",
    "approve": "Approve",
    "request_revision": "Request Revision",
    "reject": "Reject",
    "escalate": "Escalate",
    "accept_suggested_revision": "Accept Suggested Revision",
    "edit_suggested_revision": "Edit Suggested Revision",
    "discard_suggested_revision": "Discard Suggested Revision",
}


def _metrics(values: dict[str, int]) -> None:
    names = list(values)
    for start in range(0, len(names), 5):
        columns = st.columns(min(5, len(names) - start))
        for column, name in zip(columns, names[start:start + 5]):
            column.metric(name.replace("_", " ").title(), values[name])


def _load_or_reset_progress(identity: str, target: int) -> PilotProgress:
    if st.session_state.get("unified_filter_identity") != identity:
        st.session_state.unified_filter_identity = identity
        st.session_state.unified_progress = PilotProgress(target=target)
        st.session_state.unified_selected_id = None
    return st.session_state.get(
        "unified_progress", PilotProgress(target=target)
    )


def _advance(snapshot, progress: PilotProgress) -> None:
    item = review_next(snapshot, progress)
    st.session_state.unified_selected_id = (
        item.record_id if item is not None else None
    )


def run(*, configure_page: bool = True) -> None:
    if configure_page:
        st.set_page_config(page_title="Unified Review", layout="wide")
    st.title("Unified Review")
    st.warning(
        "v0.6 is a local governed version under review, not a published dataset. "
        "v0.7 has not been created, verified, approved, or published."
    )
    st.caption(
        "Recommendations are advisory. Review Next never approves, rejects, "
        "accepts a revision, creates a release, uploads, or publishes automatically."
    )
    versions = list_versions(REGISTRY_DIR)
    if not versions:
        st.info("No registered local dataset versions are available.")
        return
    version = st.sidebar.selectbox("Dataset version", versions)
    records = load_version_records(
        version, registry_dir=REGISTRY_DIR, releases_dir=RELEASES_DIR
    )
    config = load_review_config()
    assessments = load_latest_assessments(version)
    recommendations = load_latest_recommendations(
        version, reviews_root=AUTOMATED_DIR
    )
    categories = st.sidebar.multiselect(
        "Category",
        sorted({str(record["category"]) for record in records}),
        default=["business_writing"] if version == "v0.6" else [],
    )
    risks = st.sidebar.multiselect(
        "Risk level", sorted({str(record["risk_level"]) for record in records})
    )
    statuses = st.sidebar.multiselect(
        "Review status",
        sorted({str(record["review_status"]) for record in records}),
        default=["draft"],
    )
    recommendation_filter = st.sidebar.multiselect(
        "Recommendation",
        sorted({
            str(row.get("recommendation", "human_review"))
            for row in recommendations
        }),
    )
    domain_value = st.sidebar.selectbox(
        "Domain review", ["any", "required", "not required"]
    )
    eligibility_value = st.sidebar.selectbox(
        "Training eligibility", ["any", "eligible", "ineligible"]
    )
    include_finalized = st.sidebar.checkbox("Include finalized records")
    target = st.sidebar.number_input(
        "Pilot limit", min_value=1, max_value=100, value=5
    )
    reviewer = st.sidebar.text_input("Reviewer ID")
    role = st.sidebar.selectbox(
        "Reviewer role",
        ["reviewer", "technical_reviewer", "domain_reviewer", "release_manager"],
    )
    filter_arguments = {
        "category": tuple(categories),
        "risk_level": tuple(risks),
        "review_status": tuple(statuses),
        "domain_review_required": (
            True if domain_value == "required"
            else False if domain_value == "not required"
            else None
        ),
        "training_eligible": (
            True if eligibility_value == "eligible"
            else False if eligibility_value == "ineligible"
            else None
        ),
        "include_finalized": include_finalized,
    }
    if "recommendation" in getattr(QueueFilters, "__dataclass_fields__", {}):
        filter_arguments["recommendation"] = tuple(recommendation_filter)
    else:
        st.sidebar.warning(
            "An older review queue module is still cached. Restart Streamlit "
            "to enable recommendation filtering."
        )
    filters = QueueFilters(
        **filter_arguments,
    )
    snapshot = build_queue(
        records,
        version,
        config,
        assessments=assessments,
        recommendations=recommendations,
        filters=filters,
        page=1,
        page_size=500,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    identity = filter_identity(version, filters, int(target))
    progress = _load_or_reset_progress(identity, int(target))

    st.header("Active queue")
    _metrics(queue_summary(snapshot))
    st.subheader("Pilot")
    _metrics({
        key: int(value)
        for key, value in pilot_summary(
            progress,
            records,
            version=version,
            domain_review_categories=config.domain_review_categories,
        ).items()
        if isinstance(value, int)
    })
    if st.button("Review Next", type="primary"):
        _advance(snapshot, progress)
        st.rerun()

    selected_id = st.session_state.get("unified_selected_id")
    if selected_id is None:
        next_item = review_next(snapshot, progress)
        if next_item is None:
            st.success("Queue completed for this pilot and filter set.")
            st.json(pilot_summary(
                progress,
                records,
                version=version,
                domain_review_categories=config.domain_review_categories,
            ))
        else:
            st.info("Click Review Next to load the highest-priority record.")
        return
    by_id = {str(record["id"]): record for record in records}
    selected_queue_item = next(
        (
            item
            for item in snapshot.items
            if item.record_id == selected_id
        ),
        None,
    )
    if selected_id not in by_id or selected_queue_item is None:
        _advance(snapshot, progress)
        st.rerun()
        return
    record = by_id[selected_id]
    recommendation = current_recommendation(recommendations, record)
    if recommendation is None:
        st.info("This record needs a stored advisory analysis.")
        if st.button("Generate Local Advisory Analysis"):
            values, summary = analyze_records(
                records, version, config, record_id=selected_id
            )
            write_analysis_run(
                values, summary, AUTOMATED_DIR, audit_root=AUDIT_DIR
            )
            st.rerun()
        return

    st.header(f"Record {record['id']}")
    identity_col, content_col = st.columns([2, 3])
    with identity_col:
        st.json({
            "dataset_version": version,
            "record_id": record["id"],
            "revision": record["revision"],
            "sha256": record["example_sha256"],
            "review_status": record["review_status"],
            "source": record["source"],
            "license": record["license"],
            "category": record["category"],
            "risk_level": record["risk_level"],
            "training_eligible": selected_queue_item.training_eligible,
        })
    messages = {
        message["role"]: message["content"] for message in record["messages"]
    }
    with content_col:
        st.text_area("System prompt", messages["system"], disabled=True)
        st.text_area("User prompt", messages["user"], disabled=True)
        st.text_area(
            "Assistant response", messages["assistant"], disabled=True, height=180
        )

    st.subheader("Automated advisory analysis")
    st.json(recommendation.to_dict())
    suggestion = recommendation.suggested_revision
    edited_prompt = edited_response = None
    if suggestion is not None:
        st.subheader("Suggested revision")
        before, after = st.columns(2)
        with before:
            st.text_area("Original prompt", messages["user"], disabled=True)
            st.text_area(
                "Original response", messages["assistant"], disabled=True, height=180
            )
        with after:
            edited_prompt = st.text_area("Suggested prompt", suggestion.prompt)
            edited_response = st.text_area(
                "Suggested response", suggestion.response, height=180
            )
        st.json({
            "changes_summary": suggestion.changes_summary,
            "rationale": suggestion.reasons,
            "safety_impact": suggestion.safety_impact,
            "factuality_impact": suggestion.factuality_impact,
            "cultural_context_impact": suggestion.cultural_context_impact,
        })

    st.subheader("Audit history")
    st.json({
        "automated_and_human": audit_history(AUDIT_DIR, version, selected_id),
        "registry_revision_events": review_history(
            REGISTRY_DIR, version, selected_id
        ),
    })

    st.subheader("Explicit human action")
    actions = list(ACTION_LABELS)
    if suggestion is None:
        actions = [
            action for action in actions
            if "suggested_revision" not in action
        ]
    action = st.selectbox(
        "Action", actions, format_func=lambda value: ACTION_LABELS[value]
    )
    note = st.text_area("Decision note or reason")
    escalation_target = (
        st.selectbox(
            "Target review type",
            ["technical", "domain", "safety", "provenance"],
        )
        if action == "escalate" else None
    )
    confirmation = st.checkbox(
        "I explicitly confirm this final decision",
        disabled=action not in {"approve", "reject"},
    )
    if action == "approve":
        blockers = approval_blockers(record, recommendation)
        if blockers:
            st.error("Approval blocked: " + ", ".join(blockers))

    action_col, skip_col = st.columns(2)
    if action_col.button("Record Human Action"):
        try:
            if action in {
                "accept_suggested_revision",
                "edit_suggested_revision",
                "discard_suggested_revision",
            }:
                apply_revision_action(
                    REGISTRY_DIR,
                    AUDIT_DIR,
                    version,
                    selected_id,
                    action,
                    reviewer,
                    role,
                    recommendation=recommendation,
                    decision_note=note,
                    edited_prompt=edited_prompt,
                    edited_response=edited_response,
                )
            else:
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
                    confirm_approval=confirmation if action == "approve" else False,
                    confirm_rejection=confirmation if action == "reject" else False,
                    escalation_target=escalation_target,
                )
            updated_records = load_version_records(
                version, registry_dir=REGISTRY_DIR, releases_dir=RELEASES_DIR
            )
            refresh_review_outputs(
                updated_records,
                version,
                output_root=REFRESH_DIR,
                release_root=RELEASES_DIR,
            )
        except (DatasetManagementError, OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            progress = record_action_and_advance(
                progress, selected_id, action
            )
            st.session_state.unified_progress = progress
            _advance(snapshot, progress)
            st.rerun()
    if skip_col.button("Skip"):
        progress = record_action_and_advance(progress, selected_id, "skip")
        st.session_state.unified_progress = progress
        _advance(snapshot, progress)
        st.rerun()


if __name__ == "__main__":
    run()

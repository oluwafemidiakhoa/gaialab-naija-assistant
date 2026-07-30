"""Preview-first Streamlit panel for governed bulk human review."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st  # noqa: E402

from src.dataset_management import DatasetManagementError, list_versions  # noqa: E402
from src.review_automation.bulk import (  # noqa: E402
    BULK_ACTIONS,
    CONFIRMATION_PHRASE,
    BulkReviewPreview,
    build_bulk_preview,
    execute_bulk_review,
)
from src.review_automation.config import load_review_config  # noqa: E402
from src.review_automation.service import (  # noqa: E402
    load_latest_assessments,
    load_latest_recommendations,
    load_version_records,
)


REGISTRY_DIR = Path(os.getenv("GAIALAB_DATASET_REGISTRY", "data/registry"))
RELEASES_DIR = Path(os.getenv("GAIALAB_DATASET_RELEASES", "data/releases"))
AUTOMATED_DIR = Path(
    os.getenv("GAIALAB_AUTOMATED_REVIEWS", "evaluation/automated_reviews")
)
QUALITY_DIR = Path(os.getenv("GAIALAB_QUALITY_ROOT", "evaluation/quality"))
AUDIT_DIR = Path(os.getenv("GAIALAB_REVIEW_AUDIT", "evaluation/review_audit"))


def _preview_rows(preview: BulkReviewPreview) -> list[dict[str, object]]:
    return [
        {
            "record_id": item.record_id,
            "category": item.category,
            "risk": item.risk_level,
            "status": item.review_status,
            "recommendation": item.recommendation,
            "quality": item.quality_score,
            "unresolved_findings": " | ".join(item.unresolved_findings),
            "technical_review_required": item.technical_review_required,
            "domain_review_required": item.domain_review_required,
            "eligibility_blockers": " | ".join(item.eligibility_blockers),
            "allowed": item.allowed,
            "blocking_reasons": " | ".join(item.blocking_reasons),
        }
        for item in preview.items
    ]


def run(*, configure_page: bool = True) -> None:
    if configure_page:
        st.set_page_config(page_title="Bulk Governed Review", layout="wide")
    st.title("Bulk Governed Review")
    st.warning(
        "This panel never approves automatically. AI recommendations are advisory, "
        "and technical review is always separate from approval."
    )
    st.caption(
        "Write mode is bound to the authenticated local reviewer identity in "
        "GAIALAB_AUTHENTICATED_REVIEWER_ID. Every allowed record receives its own "
        "append-only human audit event."
    )
    versions = list_versions(REGISTRY_DIR)
    if not versions:
        st.info("No registered local dataset versions are available.")
        return
    version = st.selectbox("Dataset version", versions)
    records = load_version_records(
        version,
        registry_dir=REGISTRY_DIR,
        releases_dir=RELEASES_DIR,
    )
    categories = sorted({str(record.get("category", "")) for record in records})
    with st.form("bulk_preview_form"):
        category = st.selectbox("Category", categories)
        action = st.selectbox(
            "Human action",
            tuple(BULK_ACTIONS),
            format_func=lambda value: value.replace("-", " ").title(),
        )
        reviewer_id = st.text_input("Reviewer ID")
        reviewer_role = st.selectbox(
            "Reviewer role",
            (
                "reviewer",
                "technical_reviewer",
                "domain_reviewer",
                "release_manager",
            ),
        )
        decision_note = st.text_area(
            "Batch decision note",
            help="The complete note is copied into every per-record audit event.",
        )
        limit = st.number_input(
            "Maximum records", min_value=1, max_value=500, value=20
        )
        escalation_target = (
            st.selectbox(
                "Escalation target",
                ("technical", "domain", "safety", "provenance"),
            )
            if action == "escalate"
            else None
        )
        preview_requested = st.form_submit_button("Preview governed batch")

    if preview_requested:
        try:
            preview = build_bulk_preview(
                records,
                version,
                load_review_config(),
                category=category,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
                action=action,
                decision_note=decision_note,
                limit=int(limit),
                escalation_target=escalation_target,
                assessments=load_latest_assessments(
                    version, quality_root=QUALITY_DIR
                ),
                recommendations=load_latest_recommendations(
                    version, reviews_root=AUTOMATED_DIR
                ),
                audit_root=AUDIT_DIR,
            )
        except (DatasetManagementError, OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.session_state.bulk_governed_preview = preview
            st.session_state.bulk_governed_result = None

    prior_result = st.session_state.get("bulk_governed_result")
    preview = st.session_state.get("bulk_governed_preview")
    if not isinstance(preview, BulkReviewPreview):
        if prior_result:
            st.success(
                f"Last batch recorded {prior_result['records_written']} records."
            )
            st.json(prior_result)
        st.info("Create and inspect a dry-run preview before enabling write mode.")
        return

    st.subheader("Governed preview")
    columns = st.columns(3)
    columns[0].metric("Selected", preview.selected_count)
    columns[1].metric("Allowed", preview.allowed_count)
    columns[2].metric("Blocked", preview.blocked_count)
    st.code(f"Batch operation ID: {preview.batch_operation_id}")
    st.dataframe(_preview_rows(preview), use_container_width=True)
    st.json({
        "records_allowed": [
            item.record_id for item in preview.items if item.allowed
        ],
        "records_blocked": {
            item.record_id: item.blocking_reasons
            for item in preview.items
            if not item.allowed
        },
        "preview_sha256": preview.preview_sha256,
    })

    st.subheader("Explicit human execution")
    write_mode = st.checkbox(
        "Enable append-only write mode",
        help="Unchecked is always a dry run.",
    )
    confirmation = st.text_input(
        f'Type exactly: {CONFIRMATION_PHRASE}',
        type="password",
    )
    authenticated_id = os.getenv("GAIALAB_AUTHENTICATED_REVIEWER_ID")
    identity_matches = authenticated_id == preview.reviewer_id
    if not identity_matches:
        st.error(
            "Authenticated local reviewer identity is missing or does not match "
            "the preview reviewer ID."
        )
    can_execute = bool(
        write_mode
        and identity_matches
        and confirmation == CONFIRMATION_PHRASE
        and preview.allowed_count
    )
    if st.button(
        "Execute governed batch",
        type="primary",
        disabled=not can_execute,
    ):
        try:
            result = execute_bulk_review(
                preview,
                load_review_config(),
                registry_dir=REGISTRY_DIR,
                releases_dir=RELEASES_DIR,
                audit_root=AUDIT_DIR,
                assessments=load_latest_assessments(
                    version, quality_root=QUALITY_DIR
                ),
                recommendations=load_latest_recommendations(
                    version, reviews_root=AUTOMATED_DIR
                ),
                confirmation=confirmation,
                authenticated_reviewer_id=authenticated_id,
                dry_run=False,
            )
        except (DatasetManagementError, OSError, ValueError) as exc:
            st.error(str(exc))
        else:
            st.session_state.bulk_governed_result = result
            st.session_state.bulk_governed_preview = None
            st.rerun()


if __name__ == "__main__":
    run()

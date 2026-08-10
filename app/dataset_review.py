"""Streamlit interface for append-only GaiaLab dataset review."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from src.dataset_management import (
    DatasetManagementError,
    list_versions,
    review_state,
)
from src.language_governance import requires_cultural_validation
from src.review_workflow import (
    create_revision,
    record_cultural_validation,
    review_history,
    transition_review,
)


REGISTRY_DIR = Path(os.getenv("GAIALAB_DATASET_REGISTRY", "data/registry"))


def run(*, configure_page: bool = True) -> None:
    if configure_page:
        st.set_page_config(page_title="GaiaLab Dataset Review", layout="wide")
    st.title("GaiaLab Naija Dataset Review")
    st.caption(
        "Local, append-only review. Approved content is immutable; edits create "
        "a linked draft revision."
    )
    versions = list_versions(REGISTRY_DIR)
    if not versions:
        st.warning(
            "No registered dataset versions. Import one with "
            "`python scripts/dataset_platform.py import ...`."
        )
        return

    version = st.sidebar.selectbox("Dataset version", versions)
    records = review_state(REGISTRY_DIR, version)
    status_filter = st.sidebar.multiselect(
        "Review status",
        [
            "draft", "automated_reviewed", "needs_revision", "technical_reviewed",
            "domain_reviewed", "approved", "rejected", "superseded",
        ],
        default=["draft"],
    )
    category_filter = st.sidebar.multiselect(
        "Category", sorted({record["category"] for record in records})
    )
    risk_filter = st.sidebar.multiselect(
        "Risk level", sorted({record["risk_level"] for record in records})
    )
    quality_range = st.sidebar.slider("Quality range", 0, 100, (0, 100))
    action_filter = st.sidebar.multiselect(
        "Recommended action",
        ["approve_candidate", "human_review", "revise", "reject_candidate"],
    )
    filtered = [
        record
        for record in records
        if record["review_status"] in status_filter
        and (not category_filter or record["category"] in category_filter)
        and (not risk_filter or record["risk_level"] in risk_filter)
        and (
            record.get("quality_score") in (None, "")
            or quality_range[0] <= float(record["quality_score"]) <= quality_range[1]
        )
        and (
            not action_filter or record.get("recommended_action") in action_filter
        )
    ]
    if not filtered:
        st.info("No records match the selected filters.")
        return

    labels = {
        f"{record['id']} · r{record['revision']} · {record['review_status']}": record
        for record in filtered
    }
    selected = st.selectbox("Example", labels)
    record = labels[selected]
    messages = {message["role"]: message["content"] for message in record["messages"]}

    left, right = st.columns([2, 1])
    with left:
        st.text_area("System", messages["system"], height=100, disabled=True)
        user = st.text_area("User", messages["user"], height=130)
        assistant = st.text_area("Assistant", messages["assistant"], height=220)
    with right:
        st.json(
            {
                "category": record["category"],
                "risk_level": record["risk_level"],
                "source": record["source"],
                "license": record["license"],
                "example_sha256": record["example_sha256"],
                "supersedes_sha256": record["supersedes_sha256"],
                "reviewer": record["reviewer"],
                "review_date": record["review_date"],
                "quality_score": record["quality_score"],
                "recommended_action": record.get("recommended_action"),
                "quality_findings": record.get("quality_findings", []),
                "quality_warnings": record.get("quality_warnings", []),
                "language": record.get("language"),
                "cultural_review_required": requires_cultural_validation(record),
                "culturally_validated": record.get("culturally_validated", False),
                "cultural_reviewer": record.get("cultural_reviewer", ""),
                "cultural_review_timestamp": record.get("cultural_review_timestamp", ""),
                "cultural_review_record_sha256": record.get("cultural_review_record_sha256", ""),
                "governance_status": record.get("governance_status"),
            }
        )
        st.subheader("Review history")
        history = review_history(REGISTRY_DIR, version, record["id"])
        st.json([
            {
                key: event.get("review_event", {}).get(key)
                for key in (
                    "revision", "previous_status", "new_status", "reviewer_role",
                    "review_timestamp", "quality_score", "correction_required",
                )
            }
            for event in history if event.get("review_event")
        ])
        cultural_history = [
            event.get("cultural_review_event")
            for event in history if event.get("cultural_review_event")
        ]
        if cultural_history:
            st.subheader("Cultural review history")
            st.json(cultural_history)
        revisions = [
            event.get("record") for event in history if event.get("record")
        ]
        if revisions:
            previous = revisions[-2] if len(revisions) > 1 else revisions[-1]
            with st.expander("Side-by-side revision comparison"):
                before, after = st.columns(2)
                before.json({
                    "revision": previous.get("revision"),
                    "messages": previous.get("messages"),
                    "record_sha256": previous.get("example_sha256"),
                })
                after.json({
                    "revision": record.get("revision"),
                    "messages": record.get("messages"),
                    "record_sha256": record.get("example_sha256"),
                })

    reviewer = st.text_input("Reviewer name or stable reviewer ID")
    role = st.radio(
        "Reviewer role",
        ["reviewer", "technical_reviewer", "domain_reviewer", "release_manager"],
        horizontal=True,
    )
    score = st.slider("Quality score", 0, 100, 70)
    notes = st.text_area("Review notes")
    action = st.radio(
        "Decision",
        [
            "automated_reviewed", "technical_reviewed", "domain_reviewed",
            "approved", "needs_revision", "rejected",
        ],
        horizontal=True,
    )
    if st.button("Append review decision", type="primary"):
        edited_messages = [
            {"role": "system", "content": messages["system"]},
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": assistant.strip()},
        ]
        try:
            changed = edited_messages != record["messages"]
            if changed:
                updated = create_revision(
                    REGISTRY_DIR, version, record["id"], edited_messages, reviewer
                )
                result = f"Created draft revision {updated['revision']}."
            else:
                event = transition_review(
                    REGISTRY_DIR, version, record["id"], action, reviewer, role,
                    quality_score=score, review_notes=notes,
                    correction_required=action == "needs_revision",
                )
                result = f"Appended {event.new_status} for revision {event.revision}."
        except DatasetManagementError as exc:
            st.error(str(exc))
        else:
            st.success(result)
            st.rerun()

    if requires_cultural_validation(record):
        st.divider()
        st.subheader("Nigerian cultural validation")
        st.caption(
            "This is a separate content-bound human decision. It does not approve "
            "the record and must be repeated after any content revision."
        )
        cultural_notes = st.text_area("Cultural review notes")
        culturally_valid = st.radio(
            "Cultural decision",
            ["validated", "not_validated"],
            horizontal=True,
        )
        if st.button("Append cultural validation"):
            try:
                event = record_cultural_validation(
                    REGISTRY_DIR,
                    version,
                    record["id"],
                    reviewer,
                    role,
                    culturally_validated=culturally_valid == "validated",
                    review_notes=cultural_notes,
                )
            except DatasetManagementError as exc:
                st.error(str(exc))
            else:
                st.success(
                    f"Appended cultural review for revision {event.revision}; "
                    f"validated={event.culturally_validated}."
                )
                st.rerun()

    public_queue = [
        {
            "id": item["id"], "category": item["category"],
            "risk_level": item["risk_level"], "review_status": item["review_status"],
            "example_sha256": item["example_sha256"],
            "cultural_review_required": requires_cultural_validation(item),
            "culturally_validated": item.get("culturally_validated", False),
        }
        for item in filtered
    ]
    st.download_button(
        "Export review queue (no bulk approval)",
        data="\n".join(
            __import__("json").dumps(item, sort_keys=True) for item in public_queue
        ) + "\n",
        file_name=f"{version}-review-queue.jsonl",
        mime="application/x-ndjson",
    )


if __name__ == "__main__":
    run()

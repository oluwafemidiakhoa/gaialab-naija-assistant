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
    review_record,
    review_state,
)


REGISTRY_DIR = Path(os.getenv("GAIALAB_DATASET_REGISTRY", "data/registry"))


def run() -> None:
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
        "Review status", ["draft", "approved", "rejected"], default=["draft"]
    )
    category_filter = st.sidebar.multiselect(
        "Category", sorted({record["category"] for record in records})
    )
    filtered = [
        record
        for record in records
        if record["review_status"] in status_filter
        and (not category_filter or record["category"] in category_filter)
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
            }
        )

    reviewer = st.text_input("Reviewer name or stable reviewer ID")
    score = st.slider("Quality score", 0.0, 5.0, 3.0, 0.5)
    notes = st.text_area("Review notes")
    action = st.radio("Decision", ["approved", "rejected", "draft"], horizontal=True)
    if st.button("Append review decision", type="primary"):
        edited_messages = [
            {"role": "system", "content": messages["system"]},
            {"role": "user", "content": user.strip()},
            {"role": "assistant", "content": assistant.strip()},
        ]
        try:
            updated = review_record(
                REGISTRY_DIR,
                version,
                record["id"],
                action,
                reviewer,
                score,
                notes,
                edited_messages=edited_messages,
            )
        except DatasetManagementError as exc:
            st.error(str(exc))
        else:
            st.success(
                f"Appended revision {updated['revision']} with status "
                f"{updated['review_status']}."
            )
            st.rerun()


if __name__ == "__main__":
    run()

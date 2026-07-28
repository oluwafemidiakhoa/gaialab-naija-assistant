from collections import Counter
from pathlib import Path

import streamlit as st

from src.dataset_management import read_jsonl
from src.training_eligibility import assess_eligibility

st.title("Training Eligibility")
root = Path("data/releases")
versions = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
if not versions:
    st.info("No releases available.")
else:
    version = st.selectbox("Release version", versions, index=len(versions) - 1)
    rows = read_jsonl(root / version / f"{version}.jsonl")
    decisions = [assess_eligibility(row, version) for row in rows]
    st.metric("Eligible records", sum(d.eligible for d in decisions))
    st.metric("Excluded records", sum(not d.eligible for d in decisions))
    reasons = Counter(reason for decision in decisions for reason in decision.reasons)
    st.subheader("Exclusion reasons")
    st.bar_chart(dict(reasons))
    st.dataframe([
        {
            "record_id": d.record_id, "eligible": d.eligible,
            "reasons": ", ".join(d.reasons), "decision_sha256": d.decision_sha256,
        }
        for d in decisions
    ])

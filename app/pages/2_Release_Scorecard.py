import json
from collections import Counter
from pathlib import Path

import streamlit as st

from src.dataset_management import read_jsonl
from src.release_scorecard import generate_scorecard, public_scorecard
from src.training_eligibility import assess_eligibility

st.title("Dataset Release Scorecard")
releases = Path("data/releases")
versions = sorted(p.name for p in releases.iterdir() if p.is_dir()) if releases.exists() else []
if not versions:
    st.info("No immutable releases are available.")
else:
    version = st.selectbox("Release version", versions, index=len(versions) - 1)
    root = releases / version
    rows = read_jsonl(root / f"{version}.jsonl")
    decisions = [assess_eligibility(row, version) for row in rows]
    quality_path = Path("evaluation/quality") / version / "quality_assessments.jsonl"
    quality_runs = sorted(quality_path.parent.glob("run-*/quality_assessments.jsonl"))
    if quality_runs:
        quality_path = quality_runs[-1]
    assessments = read_jsonl(quality_path) if quality_path.is_file() else []
    card = public_scorecard(generate_scorecard(
        version, rows, root / "dataset_manifest.json", decisions=decisions,
        assessments=assessments,
    ))
    columns = st.columns(4)
    columns[0].metric("Records", card["record_count"])
    columns[1].metric("Eligible", card["eligible_training_count"])
    columns[2].metric("Approved", card["approved_count"])
    columns[3].metric("Integrity pass", f"{card['integrity_pass_rate']}%")
    st.subheader("Category distribution")
    st.bar_chart(card["category_distribution"])
    st.subheader("Risk distribution")
    st.bar_chart(card["risk_distribution"])
    st.subheader("Review and quality")
    st.json({
        "technical_review_completion_rate": card["technical_review_completion_rate"],
        "domain_review_completion_rate": card["domain_review_completion_rate"],
        "human_review_completion_rate": card["human_review_completion_rate"],
        "quality_distribution": card["quality_distribution"],
        "unresolved_critical_findings": card["unresolved_critical_findings"],
        "excluded_count": card["excluded_count"],
        "exclusion_reasons": dict(Counter(
            reason for decision in decisions for reason in decision.reasons
        )),
        "manifest_sha256": card["manifest_sha256"],
    })
    st.download_button(
        "Download public scorecard JSON", json.dumps(card, indent=2, sort_keys=True),
        file_name=f"{version}-scorecard.json", mime="application/json",
    )

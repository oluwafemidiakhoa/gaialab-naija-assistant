import json
from pathlib import Path

import streamlit as st

from src.dataset_management import read_jsonl
from src.release_verification import source_classification, verify_release

st.title("Public Dataset Explorer")
root = Path("data/releases")
versions = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
version = st.selectbox("Release version", versions) if versions else None
if version:
    records = read_jsonl(root / version / f"{version}.jsonl")
    record_id = st.text_input("Record ID")
    search = st.text_input("Search text")
    category = st.multiselect("Category", sorted({r["category"] for r in records}))
    risk = st.multiselect("Risk", sorted({r["risk_level"] for r in records}))
    source = st.multiselect("Source classification", sorted({source_classification(r) for r in records}))
    license_filter = st.multiselect("License", sorted({r["license"] for r in records}))
    status = st.multiselect("Review status", sorted({r["review_status"] for r in records}))
    quality = st.slider("Quality range", 0, 100, (0, 100))
    filtered = []
    for row in records:
        public = {
            "record_id": row["id"], "release_version": version,
            "category": row["category"], "risk_level": row["risk_level"],
            "source_classification": source_classification(row), "license": row["license"],
            "review_status": row["review_status"], "revision": row["revision"],
            "record_sha256": row["example_sha256"], "created_at": row["created_at"],
            "quality_score": row.get("quality_score"),
        }
        searchable = f"{row['id']} {row['messages'][1]['content']} {row['messages'][2]['content']}".casefold()
        if record_id and record_id.casefold() not in row["id"].casefold(): continue
        if search and search.casefold() not in searchable: continue
        if category and row["category"] not in category: continue
        if risk and row["risk_level"] not in risk: continue
        if source and public["source_classification"] not in source: continue
        if license_filter and row["license"] not in license_filter: continue
        if status and row["review_status"] not in status: continue
        if row.get("quality_score") not in (None, "") and not quality[0] <= row["quality_score"] <= quality[1]: continue
        filtered.append(public)
    st.dataframe(filtered)
    if filtered:
        selected = st.selectbox("Verify selected record", [r["record_id"] for r in filtered])
        st.json(verify_release(root, version=version, record_id=selected))
    st.download_button(
        "Export filtered public metadata", json.dumps(filtered, indent=2, sort_keys=True),
        file_name=f"{version}-public-metadata.json", mime="application/json",
    )

import json
from pathlib import Path

import streamlit as st

st.title("Cross-Version Benchmark Dashboard")
root = Path("evaluation/reports")
runs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "all_model_versions.json").is_file()) if root.exists() else []
if not runs:
    st.info("No cross-version benchmark report is registered.")
else:
    selected = st.selectbox("Benchmark run", [p.name for p in runs], index=len(runs) - 1)
    report = json.loads((root / selected / "all_model_versions.json").read_text())
    st.caption(
        "Model superiority is only assessed when benchmark version and scoring method match."
    )
    st.json(report)
    rates = {
        version: values.get("overall_pass_rate", 0)
        for version, values in report.get("models", {}).items()
    }
    if rates:
        st.bar_chart(rates)

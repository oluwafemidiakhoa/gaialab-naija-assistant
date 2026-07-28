"""Integrated GaiaLab dataset and model governance platform."""

import streamlit as st

st.set_page_config(page_title="GaiaLab Governance Platform", layout="wide")
st.title("GaiaLab Naija Governance Platform")
st.write(
    "Local-first review, integrity verification, scorecards, eligibility, model "
    "registry verification, benchmark reports, and public dataset exploration."
)
st.warning(
    "Automated quality scores are advisory. They never constitute human approval."
)
st.markdown(
    """
Use the pages in the sidebar:

- **Dataset Review** for append-only human decisions and revisions
- **AI-Assisted Review** for advisory prioritization and explicit human actions
- **Unified Review** for guided Review Next and controlled pilot sessions
- **Release Verification** and **Model Verification** for public certificates
- **Release Scorecard** and **Benchmark Dashboard** for reproducible reports
- **Dataset Explorer** for sanitized public metadata
- **Training Eligibility** for explainable inclusion decisions
"""
)

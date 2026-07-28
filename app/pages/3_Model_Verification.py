import json
from pathlib import Path

import streamlit as st

from src.model_registry import ModelRegistry
from src.model_verification import verify_model_release

st.title("Model Artifact Verification")
version = st.text_input("Model version")
run_id = st.text_input("Training run ID")
adapter = st.text_input("Adapter SHA-256")
manifest = st.text_input("Dataset manifest SHA-256")
if st.button("Verify model"):
    certificate = verify_model_release(
        ModelRegistry(Path("model_registry")), model_version=version or None,
        training_run_id=run_id or None, adapter_sha256=adapter or None,
        dataset_manifest_sha256=manifest or None,
    )
    st.json(certificate)
    st.download_button(
        "Download model certificate", json.dumps(certificate, indent=2, sort_keys=True),
        file_name="model-verification.json", mime="application/json",
    )

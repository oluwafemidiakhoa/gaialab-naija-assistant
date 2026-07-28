"""Public read-only Streamlit verifier for GaiaLab dataset releases."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from src.release_verification import (
    ReleaseVerificationError,
    certificate_json,
    verify_release,
)


RELEASES_DIR = Path(os.getenv("GAIALAB_RELEASES_DIR", "data/releases"))


def render(*, configure_page: bool = True) -> None:
    if configure_page:
        st.set_page_config(page_title="GaiaLab Release Verification", layout="wide")
    st.title("GaiaLab Dataset Release Verification")
    st.caption(
        "Read-only public verification. Certificates exclude reviewer identities, "
        "review notes, raw prompts, responses, and private provenance evidence."
    )

    with st.form("release-verification"):
        version = st.text_input("Release version", placeholder="v0.6")
        record_id = st.text_input("Record ID", placeholder="v06-banking-001")
        record_hash = st.text_input("Record SHA-256")
        manifest_hash = st.text_input("Manifest SHA-256")
        submitted = st.form_submit_button("Verify release")

    if not submitted:
        st.info("Enter any supported identifier and select Verify release.")
        return
    try:
        certificate = verify_release(
            RELEASES_DIR,
            version=version,
            record_id=record_id,
            record_sha256=record_hash,
            manifest_sha256=manifest_hash,
        )
    except ReleaseVerificationError as exc:
        st.error(str(exc))
        return

    status = certificate["integrity_status"]
    if status == "verified":
        st.success("Integrity verified.")
    elif status == "superseded":
        st.warning("The queried hash is preserved but has been superseded.")
    elif status == "altered":
        st.error("Integrity verification failed: published content was altered.")
    else:
        st.warning("No matching current or superseded record was found.")

    fields = {
        "Record exists": certificate["record_exists"],
        "Release version": certificate["release_version"],
        "Record ID": certificate["record_id"],
        "Record SHA-256": certificate["record_sha256"],
        "Manifest SHA-256": certificate["manifest_sha256"],
        "Category": certificate["category"],
        "Source classification": certificate["source_classification"],
        "License": certificate["license"],
        "Review status": certificate["review_status"],
        "Revision": certificate["revision"],
        "Creation timestamp": certificate["creation_timestamp"],
        "Approval timestamp": certificate["approval_timestamp"],
        "Integrity status": certificate["integrity_status"],
        "Superseded by": certificate["superseded_by"],
    }
    st.json(fields)
    payload = certificate_json(certificate)
    filename = (
        f"gaialab-certificate-{certificate['record_id'] or certificate['release_version'] or 'unknown'}.json"
    )
    st.download_button(
        "Download verification certificate",
        data=payload,
        file_name=filename,
        mime="application/json",
    )


if __name__ == "__main__":
    render()

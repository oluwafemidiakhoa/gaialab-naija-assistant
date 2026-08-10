from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_public_verification_app_is_read_only_and_renders() -> None:
    app = AppTest.from_file(ROOT / "app/dataset_verify.py", default_timeout=10)

    app.run()

    assert not app.exception
    assert app.title[0].value == "GaiaLab Dataset Release Verification"
    assert {item.label for item in app.text_input} == {
        "Release version",
        "Record ID",
        "Record SHA-256",
        "Manifest SHA-256",
    }
    assert {item.label for item in app.button} == {"Verify release"}
    assert not app.text_area


def test_integrated_streamlit_verification_page_renders() -> None:
    app = AppTest.from_file(
        ROOT / "app/pages/1_Release_Verification.py", default_timeout=10
    )

    app.run()

    assert not app.exception
    assert app.title[0].value == "GaiaLab Dataset Release Verification"

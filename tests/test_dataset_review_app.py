from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def test_review_interface_renders_registered_dataset() -> None:
    app = AppTest.from_file(ROOT / "app/dataset_review.py", default_timeout=10)

    app.run()

    assert not app.exception
    assert app.title[0].value == "GaiaLab Naija Dataset Review"
    assert {widget.label for widget in app.selectbox} == {
        "Dataset version",
        "Example",
    }
    assert {widget.label for widget in app.text_area} >= {
        "System",
        "User",
        "Assistant",
        "Review notes",
    }
    assert app.button[0].label == "Append review decision"

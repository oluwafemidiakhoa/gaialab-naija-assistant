from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize("path", [
    "app/Home.py",
    "app/pages/0_Dataset_Review.py",
    "app/pages/1_AI_Assisted_Review.py",
    "app/pages/1_Unified_Review.py",
    "app/pages/2_Release_Scorecard.py",
    "app/pages/3_Model_Verification.py",
    "app/pages/4_Benchmark_Dashboard.py",
    "app/pages/5_Dataset_Explorer.py",
    "app/pages/6_Training_Eligibility.py",
])
def test_integrated_page_renders(path):
    app = AppTest.from_file(path, default_timeout=15)
    app.run()
    assert not app.exception, path


def test_windows_paths_are_pathlib_compatible():
    path = Path("data") / "releases" / "v0.6" / "dataset_manifest.json"
    assert path.parts[-2:] == ("v0.6", "dataset_manifest.json")


def test_pages_do_not_depend_on_app_being_a_package():
    """Streamlit can reserve ``app`` for app/app.py on Windows."""
    for path in (
        Path("app/pages/0_Dataset_Review.py"),
        Path("app/pages/1_Release_Verification.py"),
        Path("app/pages/1_Unified_Review.py"),
    ):
        assert "from app." not in path.read_text(encoding="utf-8")
    assert "from app." not in Path(
        "app/unified_review.py"
    ).read_text(encoding="utf-8")

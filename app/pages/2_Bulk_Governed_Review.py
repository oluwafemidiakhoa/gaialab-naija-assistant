"""Integrated Bulk Governed Review page."""

from __future__ import annotations

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from bulk_governed_review import run  # noqa: E402


run(configure_page=False)

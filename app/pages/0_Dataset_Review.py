"""Integrated page for the append-only dataset reviewer."""

from __future__ import annotations

import sys
from pathlib import Path


# Streamlit may load app/app.py as the top-level module named ``app`` on
# Windows. Importing ``app.dataset_review`` would then incorrectly treat that
# module as a package. Import the sibling application directly instead.
APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from dataset_review import run

run(configure_page=False)

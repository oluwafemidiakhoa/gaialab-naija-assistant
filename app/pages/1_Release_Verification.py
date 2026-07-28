"""Read-only verification page for the GaiaLab dataset review application."""

from __future__ import annotations

import sys
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from dataset_verify import render


render(configure_page=False)

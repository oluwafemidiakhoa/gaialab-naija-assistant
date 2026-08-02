"""Run the deterministic v0.8 draft pipeline and refuse training-release creation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(command: list[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    try:
        run([sys.executable, "scripts/analyze_evaluation_failures.py"])
        run([sys.executable, "scripts/build_v08_failure_dataset.py"])
        run([sys.executable, "scripts/validate_v08_failure_dataset.py"])
    except subprocess.CalledProcessError as exc:
        print(f"v0.8 pipeline stopped after failed step: {exc}", file=sys.stderr)
        return exc.returncode or 1
    summary = {
        "dataset_version": "v0.8-draft",
        "pipeline_status": "passed",
        "training_release_created": False,
        "training_release_status": "refused_not_human_approved",
        "next_registry_import_command": (
            "python scripts/dataset_platform.py import --version v0.8-draft "
            "--input data/v0.8/generated/v0.8_draft.jsonl"
        ),
        "next_human_review_command": (
            "python scripts/review_automation.py build-queue --version v0.8-draft "
            "--review-status draft --training-eligible no"
        ),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

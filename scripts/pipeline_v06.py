"""Run the complete fail-fast GaiaLab Naija v0.6 dataset pipeline."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
STEPS = (
    ("Build combined JSONL and manifest", "scripts/build_v06_dataset.py"),
    ("Create deterministic stratified splits", "scripts/split_v06_dataset.py"),
    ("Validate sources and generated outputs", "scripts/validate_v06_dataset.py"),
    ("Generate dataset statistics", "scripts/dataset_statistics_v06.py"),
)


def run_pipeline() -> None:
    for number, (name, script) in enumerate(STEPS, start=1):
        print(f"[{number}/{len(STEPS)}] {name}", flush=True)
        subprocess.run(
            [sys.executable, script],
            cwd=PROJECT_ROOT,
            check=True,
        )


def main() -> int:
    try:
        run_pipeline()
    except subprocess.CalledProcessError as exc:
        print(
            f"Pipeline stopped immediately: {exc.cmd[-1]} exited with "
            f"status {exc.returncode}.",
            file=sys.stderr,
        )
        return exc.returncode or 1
    print("GaiaLab Naija v0.6 dataset pipeline completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

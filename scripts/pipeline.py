from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the GaiaLab v0.5 dataset workflow: generate, build, "
            "validate, and create statistics."
        )
    )
    parser.add_argument(
        "--skip-generate",
        action="store_true",
        help=(
            "Skip CSV-to-JSONL generation and keep the existing "
            "v0.5_new_examples.jsonl file."
        ),
    )
    return parser.parse_args()


def run_step(title: str, command: list[str]) -> None:
    print()
    print("=" * 60)
    print(title)
    print("=" * 60)
    print("Command:", " ".join(command))
    print()

    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{title} failed with exit code {result.returncode}."
        )


def main() -> int:
    args = parse_args()
    python_executable = sys.executable

    steps: list[tuple[str, list[str]]] = []

    if not args.skip_generate:
        steps.append(
            (
                "STEP 1 OF 4 - Generate JSONL from CSV",
                [
                    python_executable,
                    "scripts/generate_examples.py",
                ],
            )
        )

    steps.extend(
        [
            (
                "STEP 2 OF 4 - Build v0.5 Dataset",
                [
                    python_executable,
                    "scripts/build_v05_dataset.py",
                ],
            ),
            (
                "STEP 3 OF 4 - Validate Dataset",
                [
                    python_executable,
                    "scripts/validate_dataset.py",
                ],
            ),
            (
                "STEP 4 OF 4 - Generate Statistics",
                [
                    python_executable,
                    "scripts/dataset_statistics.py",
                ],
            ),
        ]
    )

    try:
        print()
        print("GaiaLab v0.5 Dataset Pipeline")
        print("=" * 60)
        print(f"Project root: {PROJECT_ROOT}")
        print(f"Python      : {python_executable}")

        for title, command in steps:
            run_step(title, command)

        print()
        print("=" * 60)
        print("PIPELINE SUCCESSFUL")
        print("=" * 60)
        print("Generated outputs:")
        print("  data/v0.5/v0.5_new_examples.jsonl")
        print("  data/v0.5/v0.5_training.jsonl")
        print("  data/v0.5/dataset_manifest.json")
        print("  data/v0.5/dataset_statistics.json")
        return 0

    except RuntimeError as exc:
        print()
        print("=" * 60)
        print("PIPELINE FAILED")
        print("=" * 60)
        print(exc)
        print("Fix the reported step, then run the pipeline again.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

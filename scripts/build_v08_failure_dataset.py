"""Build the deterministic, write-once v0.8 failure-driven draft dataset."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.v08_failure_dataset import (  # noqa: E402
    build_records,
    jsonl_text,
    manifest,
    readiness_diagnostics,
    statistics,
    validate_records,
    write_once_or_verify,
)

DEFAULT_OUTPUT = ROOT / "data" / "v0.8" / "generated"


def build(output_dir: Path = DEFAULT_OUTPUT) -> dict[str, object]:
    records = build_records()
    validation = validate_records(records)
    if not validation["valid"]:
        raise ValueError("generated v0.8 records failed validation")
    payloads = {
        "v0.8_draft.jsonl": jsonl_text(records),
        "dataset_manifest.json": json.dumps(manifest(records), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "dataset_statistics.json": json.dumps(statistics(records), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "validation_report.json": json.dumps(validation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "train_readiness_diagnostics.json": json.dumps(readiness_diagnostics(records), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    }
    outputs = {
        name: {"path": str(output_dir / name), "status": write_once_or_verify(output_dir / name, text)}
        for name, text in payloads.items()
    }
    return {"record_count": len(records), "outputs": outputs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(build(args.output_dir), indent=2, sort_keys=True))
    except (OSError, ValueError) as exc:
        print(f"v0.8 build failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

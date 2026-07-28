"""Generate a write-once public release scorecard."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import atomic_create, read_jsonl
from src.release_scorecard import generate_scorecard
from src.training_eligibility import assess_eligibility


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--quality-dir", type=Path)
    args = parser.parse_args()
    release = Path("data/releases") / args.version
    base_output = Path("evaluation/scorecards") / args.version
    output = args.output_dir or base_output
    try:
        if output.exists() and args.output_dir is None:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output = base_output / "runs" / timestamp
        elif output.exists():
            raise FileExistsError(f"scorecard already published: {output}")
        rows = read_jsonl(release / f"{args.version}.jsonl")
        decisions = [assess_eligibility(r, args.version) for r in rows]
        quality_dir = args.quality_dir or Path("evaluation/quality") / args.version
        quality_path = quality_dir / "quality_assessments.jsonl"
        run_files = sorted(quality_dir.glob("run-*/quality_assessments.jsonl"))
        if run_files:
            quality_path = run_files[-1]
        assessments = read_jsonl(quality_path) if quality_path.is_file() else []
        record_ids = {row["id"] for row in rows}
        assessments = [a for a in assessments if a.get("record_id") in record_ids]
        duplicates_path = release / "semantic_duplicates.json"
        duplicate_count = len(json.loads(duplicates_path.read_text(encoding="utf-8")))
        scorecard = generate_scorecard(
            args.version, rows, release / "dataset_manifest.json", decisions=decisions,
            assessments=assessments, duplicate_count=duplicate_count,
        )
        atomic_create(output / "scorecard.json", json.dumps(
            scorecard, indent=2, sort_keys=True
        ) + "\n")
        markdown = (
            f"# GaiaLab {args.version} release scorecard\n\n"
            f"- Records: {scorecard['record_count']}\n"
            f"- Training eligible: {scorecard['eligible_training_count']}\n"
            f"- Approved: {scorecard['approved_count']}\n"
            f"- Integrity pass rate: {scorecard['integrity_pass_rate']}%\n"
            f"- Manifest SHA-256: `{scorecard['manifest_sha256']}`\n"
            f"- Scorecard SHA-256: `{scorecard['scorecard_sha256']}`\n"
        )
        atomic_create(output / "scorecard.md", markdown)
        print(output)
    except (OSError, ValueError) as exc:
        print(f"Scorecard generation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

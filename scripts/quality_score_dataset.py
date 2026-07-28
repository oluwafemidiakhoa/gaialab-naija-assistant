"""Generate a write-once advisory quality assessment run."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import atomic_create, read_jsonl
from src.quality_intelligence import assess_records


def _run_dir(base: Path) -> Path:
    if not base.exists() or not any(base.iterdir()):
        return base
    stamp = datetime.now(timezone.utc).strftime("run-%Y%m%dT%H%M%S_%fZ")
    return base / stamp


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--record-id")
    parser.add_argument("--releases-dir", type=Path, default=Path("data/releases"))
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    source = args.releases_dir / args.version / f"{args.version}.jsonl"
    try:
        records = read_jsonl(source)
        if args.record_id:
            records = [record for record in records if record.get("id") == args.record_id]
            if not records:
                raise ValueError(f"record not found: {args.record_id}")
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        assessments = assess_records(records, assessed_at=timestamp)
        output = _run_dir(args.output_dir or Path("evaluation/quality") / args.version)
        rows = [assessment.__dict__ for assessment in assessments]
        scores = [row["overall_score"] for row in rows]
        summary = {
            "version": args.version,
            "record_count": len(rows),
            "average_score": round(statistics.fmean(scores), 4) if scores else None,
            "minimum_score": min(scores) if scores else None,
            "maximum_score": max(scores) if scores else None,
            "recommended_actions": dict(
                sorted(Counter(row["recommended_action"] for row in rows).items())
            ),
            "critical_findings": sum(
                finding["severity"] == "critical"
                for row in rows for finding in row["findings"]
            ),
            "human_approval_assigned": False,
        }
        atomic_create(
            output / "quality_assessments.jsonl",
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        )
        atomic_create(
            output / "quality_summary.json",
            json.dumps(summary, indent=2, sort_keys=True) + "\n",
        )
        markdown = [
            f"# Quality report: {args.version}", "",
            "> Advisory automated assessment only. No human approval is assigned.", "",
            f"- Records: {len(rows)}",
            f"- Average score: {summary['average_score']}",
            f"- Critical findings: {summary['critical_findings']}", "",
            "## Recommended actions", "",
        ]
        markdown.extend(
            f"- `{action}`: {count}"
            for action, count in summary["recommended_actions"].items()
        )
        atomic_create(output / "quality_report.md", "\n".join(markdown) + "\n")
    except (OSError, ValueError) as exc:
        print(f"Quality assessment failed: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

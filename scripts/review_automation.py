"""Build advisory review queues, analyses, and daily work packs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dataset_management import DatasetManagementError  # noqa: E402
from src.review_automation.config import (  # noqa: E402
    ReviewAutomationConfigError,
    load_review_config,
)
from src.review_automation.queue import QueueFilters, build_queue  # noqa: E402
from src.review_automation.refresh import refresh_review_outputs  # noqa: E402
from src.review_automation.service import (  # noqa: E402
    ReviewAutomationError,
    analyze_records,
    build_daily_pack,
    load_latest_assessments,
    load_latest_recommendations,
    load_version_records,
    make_provider,
    utc_now,
    write_analysis_run,
    write_daily_pack,
    write_queue_snapshot,
)


def _common(command: argparse.ArgumentParser) -> None:
    command.add_argument("--version", required=True)
    command.add_argument("--registry", type=Path, default=Path("data/registry"))
    command.add_argument("--releases", type=Path, default=Path("data/releases"))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--config", type=Path)
    commands = root.add_subparsers(dest="command", required=True)

    queue = commands.add_parser("build-queue")
    _common(queue)
    queue.add_argument("--category", action="append", default=[])
    queue.add_argument("--risk-level", action="append", default=[])
    queue.add_argument("--review-status", action="append", default=[])
    queue.add_argument("--minimum-quality-score", type=int, default=0)
    queue.add_argument("--maximum-quality-score", type=int, default=100)
    queue.add_argument(
        "--domain-review", choices=("any", "required", "not-required"), default="any"
    )
    queue.add_argument(
        "--training-eligible", choices=("any", "yes", "no"), default="any"
    )
    queue.add_argument("--include-finalized", action="store_true")
    queue.add_argument("--page", type=int, default=1)
    queue.add_argument("--page-size", type=int, default=20)
    queue.add_argument(
        "--output-dir", type=Path, default=Path("evaluation/review_queues")
    )
    queue.add_argument("--dry-run", action="store_true")

    analyze = commands.add_parser("analyze")
    _common(analyze)
    analyze.add_argument("--category")
    analyze.add_argument("--record-id")
    analyze.add_argument("--limit", type=int)
    analyze.add_argument("--force", action="store_true")
    analyze.add_argument("--provider")
    analyze.add_argument("--dry-run", action="store_true")
    analyze.add_argument(
        "--output-dir", type=Path, default=Path("evaluation/automated_reviews")
    )
    analyze.add_argument(
        "--audit-dir", type=Path, default=Path("evaluation/review_audit")
    )

    pack = commands.add_parser("daily-pack")
    _common(pack)
    pack.add_argument("--limit", type=int, default=20)
    pack.add_argument("--provider")
    pack.add_argument("--dry-run", action="store_true")
    pack.add_argument(
        "--output-dir", type=Path, default=Path("evaluation/daily_packs")
    )
    pack.add_argument(
        "--audit-dir", type=Path, default=Path("evaluation/review_audit")
    )

    refresh = commands.add_parser("refresh")
    _common(refresh)
    refresh.add_argument(
        "--output-dir", type=Path, default=Path("evaluation/review_refresh")
    )
    return root


def _optional_bool(value: str, positive: str, negative: str) -> bool | None:
    if value == positive:
        return True
    if value == negative:
        return False
    return None


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_review_config(args.config)
        records = load_version_records(
            args.version,
            registry_dir=args.registry,
            releases_dir=args.releases,
        )
        assessments = load_latest_assessments(args.version)
        recommendations = load_latest_recommendations(args.version)
        timestamp = utc_now()
        if args.command == "build-queue":
            filters = QueueFilters(
                category=tuple(args.category),
                risk_level=tuple(args.risk_level),
                review_status=tuple(args.review_status),
                minimum_quality_score=args.minimum_quality_score,
                maximum_quality_score=args.maximum_quality_score,
                domain_review_required=_optional_bool(
                    args.domain_review, "required", "not-required"
                ),
                training_eligible=_optional_bool(
                    args.training_eligible, "yes", "no"
                ),
                include_finalized=args.include_finalized,
            )
            snapshot = build_queue(
                records,
                args.version,
                config,
                assessments=assessments,
                recommendations=recommendations,
                filters=filters,
                page=args.page,
                page_size=args.page_size,
                generated_at=timestamp,
            )
            outputs = (
                {} if args.dry_run
                else {
                    key: str(value)
                    for key, value in write_queue_snapshot(
                        snapshot, args.output_dir
                    ).items()
                }
            )
            result = {**snapshot.to_dict(), "outputs": outputs, "dry_run": args.dry_run}
        elif args.command == "analyze":
            provider = make_provider(args.provider or config.default_provider)
            values, summary = analyze_records(
                records,
                args.version,
                config,
                provider=provider,
                category=args.category,
                record_id=args.record_id,
                limit=args.limit,
                force=args.force,
                prior_recommendations=recommendations,
                generated_at=timestamp,
            )
            outputs = (
                {} if args.dry_run
                else {
                    key: str(value)
                    for key, value in write_analysis_run(
                        values,
                        summary,
                        args.output_dir,
                        audit_root=args.audit_dir,
                    ).items()
                }
            )
            result = {
                **summary,
                "outputs": outputs,
                "dry_run": args.dry_run,
                "recommendations": (
                    [value.to_dict() for value in values] if args.dry_run else []
                ),
            }
        elif args.command == "daily-pack":
            provider = make_provider(args.provider or config.default_provider)
            pack = build_daily_pack(
                records,
                args.version,
                config,
                assessments=assessments,
                recommendations=recommendations,
                provider=provider,
                limit=args.limit,
                generated_at=timestamp,
            )
            outputs = (
                {} if args.dry_run
                else {
                    key: str(value)
                    for key, value in write_daily_pack(
                        pack,
                        args.output_dir,
                        audit_root=args.audit_dir,
                    ).items()
                }
            )
            result = {**pack, "outputs": outputs, "dry_run": args.dry_run}
        else:
            result = refresh_review_outputs(
                records,
                args.version,
                output_root=args.output_dir,
                release_root=args.releases,
                generated_at=timestamp,
            )
            result["outputs"] = {
                key: str(value) for key, value in result["outputs"].items()
            }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (
        DatasetManagementError,
        ReviewAutomationConfigError,
        ReviewAutomationError,
        OSError,
        ValueError,
    ) as exc:
        print(f"Review automation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

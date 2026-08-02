"""Orchestrate explicit, governed v0.8 batch-review stages safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dataset_management import atomic_create, read_jsonl  # noqa: E402
from src.review_automation.audit import audit_path  # noqa: E402
from src.review_automation.bulk import build_bulk_preview  # noqa: E402
from src.review_automation.config import load_review_config  # noqa: E402
from src.review_automation.service import (  # noqa: E402
    load_latest_assessments,
    load_latest_recommendations,
    load_version_records,
)
from src.training_eligibility import assess_eligibility  # noqa: E402


CONFIRMATION = "I HAVE REVIEWED THESE RECORDS"
DEFAULT_VERSION = "v0.8-draft"
DEFAULT_CATEGORIES = (
    "payment_received_confirmation",
    "invoice_receipt_confirmation_request",
    "duplicate_charge_refund_request",
    "unpaid_invoice_reminder",
    "supplier_delivery_follow_up",
    "nigerian_english_business_writing",
    "safety_refusal_redirection",
)
STAGES = (
    ("acknowledge", "acknowledge-analysis", "draft", "automated_reviewed"),
    ("technical_review", "technical-review", "automated_reviewed", "technical_reviewed"),
    ("approval", "approve", "technical_reviewed", "approved"),
)


@dataclass(frozen=True)
class ReviewPaths:
    registry: Path = Path("data/registry")
    releases: Path = Path("data/releases")
    audit: Path = Path("evaluation/review_audit")
    quality: Path = Path("evaluation/quality")
    refresh: Path = Path("evaluation/review_refresh")
    automated: Path = Path("evaluation/automated_reviews")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def file_sha256(path: Path) -> str:
    if not path.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def human_audit_count(paths: ReviewPaths, version: str) -> int:
    path = audit_path(paths.audit, version, human=True)
    return len(read_jsonl(path)) if path.is_file() else 0


def identity_environment(reviewer_id: str) -> dict[str, str]:
    if not reviewer_id.strip():
        raise ValueError("active-stage reviewer identity must not be empty")
    environment = os.environ.copy()
    environment["GAIALAB_AUTHENTICATED_REVIEWER_ID"] = reviewer_id.strip()
    if environment["GAIALAB_AUTHENTICATED_REVIEWER_ID"] != reviewer_id.strip():
        raise ValueError("active-stage reviewer identity mismatch")
    return environment


def assert_identity(environment: dict[str, str], reviewer_id: str) -> None:
    if environment.get("GAIALAB_AUTHENTICATED_REVIEWER_ID") != reviewer_id:
        raise ValueError("active-stage reviewer identity mismatch")


def parse_json_output(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError("command produced no JSON output")
    value = json.loads(text[start:])
    if not isinstance(value, dict):
        raise ValueError("command JSON output must be an object")
    return value


def default_runner(
    command: list[str], *, environment: dict[str, str] | None = None
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}"
        )
    return parse_json_output(completed.stdout)


def _common(version: str, paths: ReviewPaths) -> list[str]:
    return [
        "--version", version,
        "--registry", str(paths.registry),
        "--releases", str(paths.releases),
    ]


def _review_command(
    version: str,
    category: str,
    reviewer: str,
    role: str,
    action: str,
    note_path: Path,
    limit: int,
    paths: ReviewPaths,
    *,
    write: bool,
) -> list[str]:
    command = [
        sys.executable,
        "scripts/review_automation.py",
        "bulk-human-review",
        *_common(version, paths),
        "--category", category,
        "--reviewer-id", reviewer,
        "--reviewer-role", role,
        "--action", action,
        "--note-file", str(note_path),
        "--limit", str(limit),
        "--audit-dir", str(paths.audit),
        "--quality-root", str(paths.quality),
        "--refresh-root", str(paths.refresh),
        "--reviews-root", str(paths.automated),
    ]
    if write:
        command.extend(["--write", "--confirm", CONFIRMATION])
    else:
        command.append("--dry-run")
    return command


def _refresh_command(version: str, paths: ReviewPaths) -> list[str]:
    return [
        sys.executable,
        "scripts/review_automation.py",
        "refresh",
        *_common(version, paths),
        "--output-dir", str(paths.refresh),
        "--audit-dir", str(paths.audit),
    ]


def _analyze_command(version: str, category: str, paths: ReviewPaths) -> list[str]:
    return [
        sys.executable,
        "scripts/review_automation.py",
        "analyze",
        *_common(version, paths),
        "--category", category,
        "--force",
        "--output-dir", str(paths.automated),
        "--audit-dir", str(paths.audit),
    ]


def _note_text(
    category: str,
    stage: str,
    reviewer: str,
    timestamp: str,
    preview,
) -> str:
    return "\n".join((
        f"Category: {category}",
        f"Stage: {stage}",
        f"Reviewer identity: {reviewer}",
        f"Timestamp: {timestamp}",
        f"Selected count: {preview.selected_count}",
        f"Allowed count: {preview.allowed_count}",
        f"Blocked count: {preview.blocked_count}",
        "Acceptance criteria: current record hash and revision; valid transition and reviewer role; current quality assessment and audited recommendation where required; all provenance and licensing gates pass.",
        "Blocking criteria: unresolved duplicate, critical, safety, provenance, licensing, high-risk, stale-assessment, identity, transition, domain-review, or content-integrity finding.",
        "Human declaration: The named reviewer must personally inspect the selected records before write mode is used.",
        "",
    ))


def _create_note(
    directory: Path,
    category: str,
    stage: str,
    timestamp: str,
    text: str,
) -> Path:
    stamp = timestamp.replace("-", "").replace(":", "").replace("+00:00", "Z")
    base = directory / f"{category}__{stage}__{stamp}.txt"
    path = _available_path(base)
    atomic_create(path, text)
    return path


def _preview(
    records: list[dict[str, Any]],
    version: str,
    category: str,
    reviewer: str,
    role: str,
    action: str,
    note: str,
    limit: int,
    paths: ReviewPaths,
):
    return build_bulk_preview(
        records,
        version,
        load_review_config(),
        category=category,
        reviewer_id=reviewer,
        reviewer_role=role,
        action=action,
        decision_note=note,
        limit=limit,
        assessments=load_latest_assessments(
            version, quality_root=paths.quality, refresh_root=paths.refresh
        ),
        recommendations=load_latest_recommendations(
            version, reviews_root=paths.automated
        ),
        audit_root=paths.audit,
    )


def _simulate_allowed(records: list[dict[str, Any]], preview, new_status: str) -> None:
    allowed = {item.record_id for item in preview.items if item.allowed}
    for record in records:
        if record["id"] not in allowed:
            continue
        record["review_status"] = new_status
        if new_status in {"technical_reviewed", "approved"}:
            record["technical_review_completed"] = True
        if new_status == "approved":
            record["approved_revision"] = record["revision"]
            record["approved_record_sha256"] = record["example_sha256"]


def _available_path(path: Path) -> Path:
    """Return a non-existing, deterministically numbered sibling path."""
    if not path.exists():
        return path
    for revision in range(2, 10_000):
        candidate = path.with_name(f"{path.stem}.run-{revision:04d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"could not allocate append-only output path beside {path}")


def _write_reports(path: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    json_path = path if path.suffix == ".json" else path.with_suffix(".json")
    json_path = _available_path(json_path)
    markdown_path = json_path.with_suffix(".md")
    atomic_create(
        json_path,
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    lines = [
        f"# Governed review orchestration: {summary['dataset_version']}", "",
        f"- Mode: `{summary['mode']}`",
        f"- Human events before: {summary['human_events_before']}",
        f"- Human events after: {summary['human_events_after']}",
        f"- Training eligible: {summary['training_eligible_count']}", "",
        "| Category | Analyzed | Acknowledged | Technical | Approved | Blocked | Duplicates | Critical | Stale |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for item in summary["categories"]:
        lines.append(
            f"| {item['category']} | {item['analyzed_count']} | {item['acknowledged_count']} | "
            f"{item['technically_reviewed_count']} | {item['approved_count']} | {item['blocked_count']} | "
            f"{item['duplicate_blocked_count']} | {item['critical_blocked_count']} | "
            f"{item['stale_assessment_blocked_count']} |"
        )
    atomic_create(markdown_path, "\n".join(lines) + "\n")
    return json_path, markdown_path


def orchestrate(
    *,
    version: str,
    categories: tuple[str, ...],
    limit: int,
    acknowledgement_reviewer: str,
    technical_reviewer: str,
    release_manager: str,
    review_note_dir: Path,
    summary_output: Path,
    paths: ReviewPaths,
    write: bool,
    confirmation: str | None,
    stop_on_error: bool,
    stop_before_approval: bool,
    runner: Callable[..., dict[str, Any]] = default_runner,
) -> dict[str, Any]:
    if write and confirmation != CONFIRMATION:
        raise ValueError(f'write mode requires --confirm "{CONFIRMATION}"')
    if (
        write
        and os.getenv("PYTEST_CURRENT_TEST")
        and (
            paths.audit.resolve() == (ROOT / "evaluation/review_audit").resolve()
            or paths.registry.resolve() == (ROOT / "data/registry").resolve()
        )
    ):
        raise RuntimeError(
            "refusing write-mode access to the live human audit ledger from pytest"
        )
    if not 1 <= limit <= 500:
        raise ValueError("limit-per-category must be from 1 to 500")
    started = utc_now()
    human_path = audit_path(paths.audit, version, human=True)
    before_count = human_audit_count(paths, version)
    before_hash = file_sha256(human_path)
    command_log: list[list[str]] = []
    command_plan: list[list[str]] = []
    category_reports: list[dict[str, Any]] = []

    for category in categories:
        blocked_ids: set[str] = set()
        duplicate_blocked_ids: set[str] = set()
        critical_blocked_ids: set[str] = set()
        stale_assessment_ids: set[str] = set()
        report: dict[str, Any] = {
            "category": category,
            "analyzed_count": 0,
            "acknowledged_count": 0,
            "technically_reviewed_count": 0,
            "approved_count": 0,
            "blocked_count": 0,
            "duplicate_blocked_count": 0,
            "critical_blocked_count": 0,
            "stale_assessment_blocked_count": 0,
            "stages": [],
            "failures": [],
        }
        try:
            records = load_version_records(
                version, registry_dir=paths.registry, releases_dir=paths.releases
            )
            category_rows = [row for row in records if row.get("category") == category]
            if not category_rows:
                raise ValueError(f"unknown or empty category: {category}")
            completed_statuses = {"approved", "rejected", "superseded"}
            if any(
                row.get("review_status", "draft") not in completed_statuses
                for row in category_rows
            ):
                command = _analyze_command(version, category, paths)
                command_plan.append(command)
                command_log.append(command)
                result = runner(command)
                report["analyzed_count"] = int(
                    result.get("recommendation_count", len(category_rows))
                )
            else:
                report["stages"].append({
                    "stage": "analyze",
                    "status": "skipped_completed_category",
                })

            projected = [dict(row) for row in load_version_records(
                version, registry_dir=paths.registry, releases_dir=paths.releases
            )]
            for stage, action, required_status, new_status in STAGES:
                # Always reload the effective append-only audit state before a
                # stage. Dry-run projections remain in memory and never become
                # official state.
                load_version_records(
                    version,
                    registry_dir=paths.registry,
                    releases_dir=paths.releases,
                )
                if stage == "approval" and stop_before_approval:
                    report["stages"].append({"stage": stage, "status": "stopped_by_option"})
                    break
                current_records = (
                    load_version_records(
                        version, registry_dir=paths.registry, releases_dir=paths.releases
                    ) if write else projected
                )
                candidates = [
                    row for row in current_records
                    if row.get("category") == category
                    and row.get("review_status") == required_status
                ]
                if not candidates:
                    report["stages"].append({"stage": stage, "status": "skipped_completed_or_not_ready"})
                    continue
                reviewer, role = (
                    (acknowledgement_reviewer, "reviewer") if stage == "acknowledge"
                    else (technical_reviewer, "technical_reviewer") if stage == "technical_review"
                    else (release_manager, "release_manager")
                )
                provisional = _preview(
                    current_records, version, category, reviewer, role, action,
                    "Provisional preview used only to calculate governed note counts.",
                    limit, paths,
                )
                timestamp = utc_now()
                note_text = _note_text(category, stage, reviewer, timestamp, provisional)
                note_path = _create_note(
                    review_note_dir, category, stage, timestamp, note_text
                )
                preview_audit_hash = file_sha256(human_path)
                final_preview = _preview(
                    current_records, version, category, reviewer, role, action,
                    note_text, limit, paths,
                )
                for item in final_preview.items:
                    item_reasons = set(item.blocking_reasons)
                    if item_reasons:
                        blocked_ids.add(item.record_id)
                    if "unresolved_duplicate_finding" in item_reasons:
                        duplicate_blocked_ids.add(item.record_id)
                    if "unresolved_critical_finding" in item_reasons:
                        critical_blocked_ids.add(item.record_id)
                    if "current_quality_assessment_missing" in item_reasons:
                        stale_assessment_ids.add(item.record_id)
                stage_report = {
                    "stage": stage,
                    "status": "previewed" if not write else "pending_write",
                    "selected_count": final_preview.selected_count,
                    "allowed_count": final_preview.allowed_count,
                    "blocked_count": final_preview.blocked_count,
                    "records_allowed": [item.record_id for item in final_preview.items if item.allowed],
                    "records_blocked": {
                        item.record_id: list(item.blocking_reasons)
                        for item in final_preview.items if not item.allowed
                    },
                    "preview_sha256": final_preview.preview_sha256,
                    "note_file": str(note_path),
                }
                command = _review_command(
                    version, category, reviewer, role, action, note_path,
                    limit, paths, write=write,
                )
                command_plan.append(command)
                if write:
                    if file_sha256(human_path) != preview_audit_hash:
                        raise RuntimeError(
                            "human audit state changed after preview; refusing stale selection"
                        )
                    audit_hash = preview_audit_hash
                    audit_count = human_audit_count(paths, version)
                    environment = identity_environment(reviewer)
                    assert_identity(environment, reviewer)
                    command_log.append(command)
                    result = runner(command, environment=environment)
                    written_preview = result.get("preview", {})
                    if written_preview.get("preview_sha256") != final_preview.preview_sha256:
                        raise RuntimeError("preview/write hash mismatch; refusing stale selection")
                    execution = result.get("execution", {})
                    written = int(execution.get("records_written", 0))
                    if final_preview.allowed_count and not written:
                        raise RuntimeError("allowed preview produced no human audit events")
                    if audit_hash == file_sha256(human_path) and written:
                        raise RuntimeError("reported writes did not change the human audit ledger")
                    if human_audit_count(paths, version) != audit_count + written:
                        raise RuntimeError(
                            "human audit event count changed unexpectedly during execution"
                        )
                    stage_report["status"] = "written"
                    stage_report["records_written"] = written
                    if stage == "acknowledge": report["acknowledged_count"] += written
                    elif stage == "technical_review": report["technically_reviewed_count"] += written
                    else: report["approved_count"] += written
                else:
                    _simulate_allowed(projected, final_preview, new_status)
                    if stage == "acknowledge": report["acknowledged_count"] += final_preview.allowed_count
                    elif stage == "technical_review": report["technically_reviewed_count"] += final_preview.allowed_count
                    else: report["approved_count"] += final_preview.allowed_count
                report["stages"].append(stage_report)
                refresh_command = _refresh_command(version, paths)
                command_plan.append(refresh_command)
                if write:
                    command_log.append(refresh_command)
                    runner(refresh_command)
            report["blocked_count"] = len(blocked_ids)
            report["duplicate_blocked_count"] = len(duplicate_blocked_ids)
            report["critical_blocked_count"] = len(critical_blocked_ids)
            report["stale_assessment_blocked_count"] = len(stale_assessment_ids)
            category_reports.append(report)
        except Exception as exc:
            report["failures"].append(str(exc))
            report["blocked_count"] = len(blocked_ids)
            report["duplicate_blocked_count"] = len(duplicate_blocked_ids)
            report["critical_blocked_count"] = len(critical_blocked_ids)
            report["stale_assessment_blocked_count"] = len(stale_assessment_ids)
            category_reports.append(report)
            if stop_on_error:
                break

    final_records = load_version_records(
        version, registry_dir=paths.registry, releases_dir=paths.releases
    )
    assessments = load_latest_assessments(
        version, quality_root=paths.quality, refresh_root=paths.refresh
    )
    assessment_by_id = {str(row.get("record_id")): row for row in assessments}
    eligible = sum(
        assess_eligibility(
            row,
            version,
            critical_findings=assessment_by_id.get(str(row["id"]), {}).get("findings", ()),
        ).eligible
        for row in final_records
    )
    after_count = human_audit_count(paths, version)
    after_hash = file_sha256(human_path)
    if not write and (before_count != after_count or before_hash != after_hash):
        raise RuntimeError("dry-run changed the human audit ledger")
    summary = {
        "schema": "gaialab.v08-governed-review-orchestration.v1",
        "dataset_version": version,
        "mode": "write" if write else "dry_run",
        "started_at": started,
        "completed_at": utc_now(),
        "stop_before_approval": stop_before_approval,
        "categories": category_reports,
        "final_status_counts": dict(sorted(Counter(
            str(row.get("review_status", "draft")) for row in final_records
        ).items())),
        "training_eligible_count": eligible,
        "human_events_before": before_count,
        "human_events_after": after_count,
        "human_audit_event_count": after_count,
        "human_audit_unchanged": before_hash == after_hash,
        "failures": [
            {"category": item["category"], "errors": item["failures"]}
            for item in category_reports if item["failures"]
        ],
        "commands_executed": command_log,
        "commands_planned": command_plan,
        "training_performed": False,
        "release_created": False,
        "publication_performed": False,
    }
    json_path, markdown_path = _write_reports(summary_output, summary)
    summary["summary_outputs"] = {"json": str(json_path), "markdown": str(markdown_path)}
    return summary


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--version", default=DEFAULT_VERSION)
    selection = root.add_mutually_exclusive_group(required=True)
    selection.add_argument("--categories", nargs="+")
    selection.add_argument("--all-remaining-categories", action="store_true")
    root.add_argument("--limit-per-category", type=int, default=20)
    root.add_argument("--reviewer-id", default="olu-reviewer-001")
    root.add_argument("--technical-reviewer-id", default="olu-technical-001")
    root.add_argument("--release-manager-id", default="olu-release-001")
    root.add_argument("--review-note-dir", type=Path, default=Path("review_notes/v0.8"))
    mode = root.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--write", action="store_true")
    root.add_argument("--confirm")
    root.add_argument("--stop-on-error", action="store_true")
    root.add_argument("--stop-before-approval", action="store_true")
    root.add_argument("--summary-output", type=Path, default=Path("evaluation/review_orchestration/v0.8-draft/summary.json"))
    root.add_argument("--registry", type=Path, default=Path("data/registry"))
    root.add_argument("--releases", type=Path, default=Path("data/releases"))
    root.add_argument("--audit-root", type=Path, default=Path("evaluation/review_audit"))
    root.add_argument("--quality-root", type=Path, default=Path("evaluation/quality"))
    root.add_argument("--refresh-root", type=Path, default=Path("evaluation/review_refresh"))
    root.add_argument("--automated-root", type=Path, default=Path("evaluation/automated_reviews"))
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    categories = (
        DEFAULT_CATEGORIES if args.all_remaining_categories
        else tuple(
            part for value in args.categories
            for part in value.split(",") if part
        )
    )
    try:
        summary = orchestrate(
            version=args.version,
            categories=categories,
            limit=args.limit_per_category,
            acknowledgement_reviewer=args.reviewer_id,
            technical_reviewer=args.technical_reviewer_id,
            release_manager=args.release_manager_id,
            review_note_dir=args.review_note_dir,
            summary_output=args.summary_output,
            paths=ReviewPaths(
                registry=args.registry, releases=args.releases,
                audit=args.audit_root, quality=args.quality_root,
                refresh=args.refresh_root, automated=args.automated_root,
            ),
            write=args.write,
            confirmation=args.confirm,
            stop_on_error=args.stop_on_error,
            stop_before_approval=args.stop_before_approval,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if summary["failures"] else 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"governed v0.8 orchestration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

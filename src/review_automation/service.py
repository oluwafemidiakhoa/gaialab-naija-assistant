"""Read-only orchestration and write-once outputs for Stage 2 review automation."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.dataset_management import (
    atomic_create,
    read_jsonl,
    review_state,
    snapshot_path,
)
from src.review_automation.analyzer import ReviewAnalyzer
from src.review_automation.audit import append_automated_events, automated_event
from src.review_automation.config import ReviewAutomationConfig
from src.review_automation.models import AdvisoryRecommendation
from src.review_automation.providers import MockReviewProvider, ReviewProvider
from src.review_automation.queue import QueueSnapshot, build_queue


class ReviewAutomationError(ValueError):
    """Raised when a safe review-automation operation cannot complete."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_version(version: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ReviewAutomationError("dataset version contains unsafe characters")
    return version


def load_version_records(
    version: str,
    *,
    registry_dir: Path = Path("data/registry"),
    releases_dir: Path = Path("data/releases"),
) -> list[dict[str, Any]]:
    """Load current review state, falling back to an immutable release."""
    safe = _safe_version(version)
    if snapshot_path(registry_dir, safe).is_file():
        return review_state(registry_dir, safe)
    release = releases_dir / safe / f"{safe}.jsonl"
    if release.is_file():
        return read_jsonl(release)
    raise ReviewAutomationError(f"dataset version not found: {safe}")


def _latest_jsonl(root: Path, filename: str) -> Path | None:
    candidates = [root / filename, *sorted(root.glob(f"run-*/{filename}"))]
    available = [path for path in candidates if path.is_file()]
    return available[-1] if available else None


def load_latest_assessments(
    version: str,
    *,
    quality_root: Path = Path("evaluation/quality"),
    refresh_root: Path = Path("evaluation/review_refresh"),
) -> list[dict[str, Any]]:
    """Load the newest assessment run from quality scoring or review refresh.

    Refresh reports intentionally live separately from standalone quality
    reports. Both contain the same governed assessment schema, so downstream
    review must consider both locations. The selected rows are still checked
    against the current record SHA-256 by the decision workflow.
    """
    safe = _safe_version(version)
    roots = tuple(dict.fromkeys((quality_root / safe, refresh_root / safe)))
    candidates = {
        path
        for root in roots
        for path in (
            root / "quality_assessments.jsonl",
            *root.glob("run-*/quality_assessments.jsonl"),
        )
        if path.is_file()
    }
    if not candidates:
        return []
    runs: list[tuple[str, str, list[dict[str, Any]]]] = []
    for path in candidates:
        rows = read_jsonl(path)
        assessed_at = max(
            (str(row.get("assessed_at", "")) for row in rows),
            default="",
        )
        runs.append((assessed_at, path.as_posix(), rows))
    return max(runs, key=lambda item: (item[0], item[1]))[2]


def load_latest_recommendations(
    version: str,
    *,
    reviews_root: Path = Path("evaluation/automated_reviews"),
) -> list[dict[str, Any]]:
    root = reviews_root / _safe_version(version)
    candidates = [
        path for path in (
            root / "recommendations.jsonl",
            *sorted(root.glob("run-*/recommendations.jsonl")),
        )
        if path.is_file()
    ]
    latest: dict[str, tuple[str, str, int, dict[str, Any]]] = {}
    for path in candidates:
        for line_number, row in enumerate(read_jsonl(path), start=1):
            record_id = str(row.get("record_id", ""))
            if not record_id:
                continue
            key = (
                str(row.get("generation_timestamp", "")),
                path.as_posix(),
                line_number,
            )
            prior = latest.get(record_id)
            if prior is None or key > prior[:3]:
                latest[record_id] = (*key, row)
    return [latest[record_id][3] for record_id in sorted(latest)]


def _run_directory(base: Path, timestamp: str) -> Path:
    if not base.exists() or not any(base.iterdir()):
        return base
    stamp = timestamp.replace("-", "").replace(":", "").replace("+00:00", "Z")
    candidate = base / f"run-{stamp}"
    suffix = 1
    while candidate.exists():
        candidate = base / f"run-{stamp}-{suffix}"
        suffix += 1
    return candidate


def _write_json(path: Path, value: Any) -> None:
    atomic_create(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_queue_snapshot(
    snapshot: QueueSnapshot,
    output_root: Path,
) -> dict[str, Path]:
    """Publish JSON and Markdown queue summaries without overwriting a prior run."""
    output = _run_directory(
        output_root / snapshot.dataset_version, snapshot.generated_at
    )
    json_path = output / "review_queue.json"
    markdown_path = output / "review_queue.md"
    _write_json(json_path, snapshot.to_dict())
    lines = [
        f"# Review queue: {snapshot.dataset_version}",
        "",
        "> Advisory prioritization only. Queue position is not a human decision.",
        "",
        f"- Generated: {snapshot.generated_at}",
        f"- Matching records: {snapshot.total_matching}",
        f"- Excluded finalized records: {snapshot.excluded_finalized}",
        f"- Snapshot SHA-256: `{snapshot.snapshot_sha256}`",
        "",
        "| Priority | Record | Category | Risk | Quality | Recommendation |",
        "| ---: | --- | --- | --- | ---: | --- |",
    ]
    lines.extend(
        f"| {index} | {item.record_id} | {item.category} | "
        f"{item.effective_risk} | {item.quality_score} | {item.recommendation} |"
        for index, item in enumerate(snapshot.items, start=1)
    )
    atomic_create(markdown_path, "\n".join(lines) + "\n")
    return {"json": json_path, "markdown": markdown_path}


def make_provider(name: str) -> ReviewProvider | None:
    """Resolve built-in offline providers; external adapters are caller-supplied."""
    normalized = name.strip().casefold()
    if normalized == "local":
        return None
    if normalized == "mock":
        return MockReviewProvider({"malformed": "forces safe local fallback"})
    raise ReviewAutomationError(
        "external providers require an explicitly configured programmatic adapter"
    )


def analyze_records(
    records: Sequence[dict[str, Any]],
    version: str,
    config: ReviewAutomationConfig,
    *,
    provider: ReviewProvider | None = None,
    category: str | None = None,
    record_id: str | None = None,
    limit: int | None = None,
    force: bool = False,
    prior_recommendations: Iterable[dict[str, Any]] = (),
    generated_at: str | None = None,
) -> tuple[list[AdvisoryRecommendation], dict[str, Any]]:
    """Generate recommendations only; official review state is never written."""
    if limit is not None and limit < 1:
        raise ReviewAutomationError("limit must be positive")
    timestamp = generated_at or utc_now()
    prior = {
        (str(item.get("record_id")), str(item.get("input_record_sha256")))
        for item in prior_recommendations
    }
    selected = [
        record for record in sorted(records, key=lambda row: str(row.get("id", "")))
        if (category is None or record.get("category") == category)
        and (record_id is None or record.get("id") == record_id)
    ]
    if limit is not None:
        selected = selected[:limit]
    analyzer = ReviewAnalyzer(config, provider=provider)
    results: list[AdvisoryRecommendation] = []
    skipped = 0
    for record in selected:
        identity = (
            str(record.get("id", "")),
            str(record.get("example_sha256", "")),
        )
        if not force and identity in prior:
            skipped += 1
            continue
        results.append(analyzer.analyze(
            record, records=records, generated_at=timestamp
        ))
    summary = {
        "dataset_version": version,
        "generated_at": timestamp,
        "selected_count": len(selected),
        "recommendation_count": len(results),
        "skipped_existing_count": skipped,
        "official_status_changes": 0,
        "human_approval_assigned": False,
        "provider": provider.name if provider else "local",
        "recommendation_counts": dict(sorted(Counter(
            result.recommendation.value for result in results
        ).items())),
    }
    return results, summary


def write_analysis_run(
    recommendations: Sequence[AdvisoryRecommendation],
    summary: dict[str, Any],
    output_root: Path,
    *,
    audit_root: Path | None = None,
) -> dict[str, Path]:
    """Write recommendations and summaries atomically to a new run directory."""
    output = _run_directory(
        output_root / str(summary["dataset_version"]),
        str(summary["generated_at"]),
    )
    recommendations_path = output / "recommendations.jsonl"
    audit_path = output / "automated_audit.jsonl"
    summary_path = output / "analysis_summary.json"
    report_path = output / "analysis_report.md"
    atomic_create(
        recommendations_path,
        "".join(
            json.dumps(
                recommendation.to_dict(), ensure_ascii=False, sort_keys=True
            ) + "\n"
            for recommendation in recommendations
        ),
    )
    events = [automated_event(recommendation) for recommendation in recommendations]
    atomic_create(
        audit_path,
        "".join(
            json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n"
            for event in events
        ),
    )
    if audit_root is not None:
        append_automated_events(audit_root, recommendations)
    _write_json(summary_path, summary)
    lines = [
        f"# Automated review: {summary['dataset_version']}",
        "",
        "> Recommendations are advisory. No official review status changed.",
        "",
        f"- Recommendations: {summary['recommendation_count']}",
        f"- Skipped existing: {summary['skipped_existing_count']}",
        f"- Provider: {summary['provider']}",
        "- Human approvals assigned: 0",
        "",
        "## Recommendation counts",
        "",
    ]
    lines.extend(
        f"- `{name}`: {count}"
        for name, count in summary["recommendation_counts"].items()
    )
    atomic_create(report_path, "\n".join(lines) + "\n")
    return {
        "recommendations": recommendations_path,
        "automated_audit": audit_path,
        "summary": summary_path,
        "markdown": report_path,
    }


def build_daily_pack(
    records: Sequence[dict[str, Any]],
    version: str,
    config: ReviewAutomationConfig,
    *,
    assessments: Iterable[dict[str, Any]] = (),
    recommendations: Iterable[dict[str, Any]] = (),
    provider: ReviewProvider | None = None,
    limit: int = 20,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a prioritized advisory work package without changing review state."""
    if not 1 <= limit <= 500:
        raise ReviewAutomationError("daily pack limit must be from 1 to 500")
    timestamp = generated_at or utc_now()
    snapshot = build_queue(
        records,
        version,
        config,
        assessments=assessments,
        recommendations=recommendations,
        page=1,
        page_size=limit,
        generated_at=timestamp,
    )
    by_id = {str(record["id"]): record for record in records}
    analyzer = ReviewAnalyzer(config, provider=provider)
    entries = []
    for item in snapshot.items:
        recommendation = analyzer.analyze(
            by_id[item.record_id], records=records, generated_at=timestamp
        )
        findings_count = sum(len(getattr(recommendation, field)) for field in (
            "language_grammar_findings", "safety_findings", "factuality_concerns",
            "cultural_context_concerns", "ambiguity_findings",
            "unsupported_claim_indicators", "missing_citation_indicators",
            "high_risk_domain_indicators",
        ))
        complexity = (
            "high" if item.critical_findings or item.domain_review_required
            else "medium" if item.high_findings or findings_count >= 3
            else "low"
        )
        entries.append({
            "record_id": item.record_id,
            "category": item.category,
            "risk_level": item.risk_level,
            "effective_risk": item.effective_risk,
            "quality_score": item.quality_score,
            "recommendation": recommendation.recommendation.value,
            "key_findings": list(
                recommendation.safety_findings
                + recommendation.factuality_concerns
                + recommendation.ambiguity_findings
            ),
            "domain_review_required": recommendation.domain_review_required,
            "suggested_revision": (
                asdict(recommendation.suggested_revision)
                if recommendation.suggested_revision else None
            ),
            "estimated_review_complexity": complexity,
            "unresolved_critical_issues": item.critical_findings,
            "recommendation_hash": recommendation.recommendation_hash,
            "advisory_analysis": recommendation.to_dict(),
        })
    return {
        "pack_schema": "gaialab.daily-review-pack.v1",
        "dataset_version": version,
        "generated_at": timestamp,
        "limit": limit,
        "record_count": len(entries),
        "official_status_changes": 0,
        "records": entries,
    }


def write_daily_pack(
    pack: dict[str, Any],
    output_root: Path,
    *,
    audit_root: Path | None = None,
) -> dict[str, Path]:
    """Write a daily pack to a new directory and refuse silent replacement."""
    output = _run_directory(
        output_root / str(pack["dataset_version"]), str(pack["generated_at"])
    )
    json_path = output / "daily_review_pack.json"
    audit_path = output / "automated_audit.jsonl"
    markdown_path = output / "daily_review_pack.md"
    _write_json(json_path, pack)
    recommendations = [
        AdvisoryRecommendation.from_dict(row["advisory_analysis"])
        for row in pack["records"]
    ]
    events = [automated_event(recommendation) for recommendation in recommendations]
    atomic_create(
        audit_path,
        "".join(
            json.dumps(asdict(event), ensure_ascii=False, sort_keys=True) + "\n"
            for event in events
        ),
    )
    if audit_root is not None:
        append_automated_events(audit_root, recommendations)
    lines = [
        f"# Daily review pack: {pack['dataset_version']}",
        "",
        "> Advisory work package only. Human decisions remain separate.",
        "",
        f"- Generated: {pack['generated_at']}",
        f"- Records: {pack['record_count']}",
        "",
        "| Record | Category | Risk | Recommendation | Complexity |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {row['record_id']} | {row['category']} | {row['effective_risk']} | "
        f"{row['recommendation']} | {row['estimated_review_complexity']} |"
        for row in pack["records"]
    )
    atomic_create(markdown_path, "\n".join(lines) + "\n")
    return {
        "json": json_path,
        "automated_audit": audit_path,
        "markdown": markdown_path,
    }

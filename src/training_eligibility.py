"""Deterministic training eligibility and leakage-safe split construction."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from src.dataset_management import example_sha256
from src.language_governance import cultural_validation_is_current, requires_cultural_validation

ALLOWED_LICENSES = {"CC0-1.0", "CC-BY-4.0", "MIT", "Apache-2.0"}
DOMAIN_REVIEW_CATEGORIES = {"healthcare", "banking", "government_services"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()


@dataclass(frozen=True)
class EligibilityDecision:
    record_id: str
    eligible: bool
    reasons: list[str]
    record_sha256: str
    release_version: str
    checked_at: str
    decision_sha256: str


def assess_eligibility(
    record: dict[str, Any],
    release_version: str,
    *,
    critical_findings: Iterable[dict[str, Any]] = (),
    duplicate_ids: set[str] | None = None,
    now: Callable[[], str] = utc_now,
) -> EligibilityDecision:
    reasons: list[str] = []
    status = record.get("review_status")
    if status != "approved":
        reasons.append("not_approved")
    if not (
        record.get("technical_review_completed")
        or status in {"technical_reviewed", "domain_reviewed", "approved"}
        or record.get("approved_revision")
    ):
        reasons.append("technical_review_incomplete")
    if record.get("category") in DOMAIN_REVIEW_CATEGORIES and not (
        record.get("domain_review_completed")
        or record.get("domain_review_timestamp")
    ):
        reasons.append("domain_review_incomplete")
    if requires_cultural_validation(record) and not cultural_validation_is_current(record):
        reasons.append("cultural_validation_incomplete")
    source = str(record.get("source", "")).strip()
    if not source or source.casefold() in {"unknown", "provenance_unknown"}:
        reasons.append("provenance_incomplete")
    license_name = str(record.get("license", "")).strip()
    if not license_name:
        reasons.append("license_missing")
    elif license_name not in ALLOWED_LICENSES:
        reasons.append("license_not_allowed")
    recorded_hash = str(record.get("example_sha256", ""))
    if recorded_hash != example_sha256(record):
        reasons.append("content_hash_mismatch")
    if status == "superseded" or record.get("superseded_by_sha256"):
        reasons.append("superseded")
    if status == "rejected":
        reasons.append("rejected")
    if any(
        f.get("severity") == "critical" and not f.get("resolved", False)
        for f in critical_findings
    ):
        reasons.append("unresolved_critical_finding")
    if record.get("dataset_version") != release_version:
        reasons.append("wrong_release")
    if duplicate_ids and record.get("id") in duplicate_ids:
        reasons.append("duplicate")
    payload = {
        "record_id": str(record.get("id", "")),
        "eligible": not reasons,
        "reasons": sorted(set(reasons)),
        "record_sha256": recorded_hash,
        "release_version": release_version,
        "checked_at": now(),
    }
    return EligibilityDecision(**payload, decision_sha256=canonical_hash(payload))


def deterministic_splits(
    records: Iterable[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Split each category/risk stratum deterministically (80/10/10)."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[(record["category"], record["risk_level"])].append(record)
    result = {"training": [], "validation": [], "held_out_benchmark": []}
    for key in sorted(groups):
        ordered = sorted(
            groups[key],
            key=lambda r: hashlib.sha256(
                f"gaialab-split-v1:{r['id']}:{r['example_sha256']}".encode()
            ).hexdigest(),
        )
        count = len(ordered)
        validation = 1 if count >= 3 else 0
        benchmark = 1 if count >= 5 else 0
        result["held_out_benchmark"].extend(ordered[:benchmark])
        result["validation"].extend(ordered[benchmark:benchmark + validation])
        result["training"].extend(ordered[benchmark + validation:])
    return {name: sorted(rows, key=lambda r: r["id"]) for name, rows in result.items()}


def assert_no_benchmark_leakage(splits: dict[str, list[dict[str, Any]]]) -> None:
    def normalized(record: dict[str, Any]) -> str:
        text = record["messages"][1]["content"].casefold()
        return " ".join("".join(c if c.isalnum() else " " for c in text).split())
    train = splits["training"] + splits["validation"]
    benchmark = splits["held_out_benchmark"]
    if {r["id"] for r in train} & {r["id"] for r in benchmark}:
        raise ValueError("benchmark record ID leakage detected")
    if {normalized(r) for r in train} & {normalized(r) for r in benchmark}:
        raise ValueError("benchmark prompt leakage detected")


def decisions_json(decisions: Iterable[EligibilityDecision]) -> list[dict[str, Any]]:
    return [asdict(decision) for decision in decisions]

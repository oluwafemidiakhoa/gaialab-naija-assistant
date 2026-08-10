"""Governance helpers for Nigerian-language review candidates.

Synthetic language benchmarks remain regression fixtures. This module only stages
copies as draft dataset-review candidates and provides content-bound cultural
validation checks for downstream training eligibility.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


LANGUAGE_GOVERNANCE_VERSION = "gaialab-naija-language-governance/0.1.0"
LANGUAGE_REVIEW_SOURCE_PREFIX = "gaialab-naija-language-review:"
NIGERIAN_LANGUAGE_LABELS = {
    "nigerian pidgin",
    "nigerian english",
    "pcm",
    "pcm-ng",
    "en-ng",
}


def _language_label(record: Mapping[str, Any]) -> str:
    return str(record.get("language") or record.get("locale") or "").strip().casefold()


def requires_cultural_validation(record: Mapping[str, Any]) -> bool:
    """Return whether a record must carry current Nigerian cultural review.

    Staged candidates use a source prefix that is part of the dataset's canonical
    content hash, so removing the requirement by editing only mutable metadata
    cannot bypass the training gate.
    """
    source = str(record.get("source") or "").strip().casefold()
    return (
        source.startswith(LANGUAGE_REVIEW_SOURCE_PREFIX.casefold())
        or _language_label(record) in NIGERIAN_LANGUAGE_LABELS
        or record.get("cultural_review_required") is True
    )


def cultural_validation_is_current(record: Mapping[str, Any]) -> bool:
    """Require an affirmative human validation bound to the exact content hash."""
    if not requires_cultural_validation(record):
        return True
    record_sha256 = str(record.get("example_sha256") or "")
    return bool(
        record.get("culturally_validated") is True
        and record.get("cultural_review_completed") is True
        and str(record.get("cultural_reviewer") or "").strip()
        and str(record.get("cultural_review_timestamp") or "").strip()
        and record_sha256
        and str(record.get("cultural_review_record_sha256") or "") == record_sha256
    )


def _fixture_risk(disposition: str) -> str:
    return "high" if disposition.upper() in {"REWRITE", "ESCALATE", "BLOCK"} else "medium"


def stage_trust_fixture_records(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_path: str,
) -> list[dict[str, Any]]:
    """Convert synthetic trust fixtures into governed *draft* review candidates.

    This function never marks a record culturally validated, approved, or
    training eligible. Human reviewers must use the append-only review workflow.
    """
    staged: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in rows:
        fixture_id = str(row.get("id") or "").strip()
        language = str(row.get("language") or "").strip()
        user_message = str(row.get("user_message") or "").strip()
        assistant_response = str(row.get("assistant_response") or "").strip()
        if not fixture_id or not language or not user_message or not assistant_response:
            raise ValueError("language trust fixture is missing required fields")
        if row.get("synthetic") is not True:
            raise ValueError(f"fixture {fixture_id} must be explicitly synthetic")
        if row.get("culturally_validated") is not False:
            raise ValueError(
                f"fixture {fixture_id} must remain culturally unvalidated at staging time"
            )
        if language.casefold() not in NIGERIAN_LANGUAGE_LABELS:
            raise ValueError(f"fixture {fixture_id} has unsupported language label: {language}")

        record_id = f"naija-language-{fixture_id}"
        if record_id in seen_ids:
            raise ValueError(f"duplicate staged record id: {record_id}")
        seen_ids.add(record_id)
        expected_disposition = str(row.get("expected_disposition") or "ALLOW")
        staged.append(
            {
                "id": record_id,
                "category": "banking",
                "risk_level": _fixture_risk(expected_disposition),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a Nigerian fintech support assistant. Answer accurately "
                            "and do not invent transaction state, account state, fees, or timelines."
                        ),
                    },
                    {"role": "user", "content": user_message},
                    {"role": "assistant", "content": assistant_response},
                ],
                "source": f"{LANGUAGE_REVIEW_SOURCE_PREFIX}{source_path}#{fixture_id}",
                "license": "CC0-1.0",
                "review_status": "draft",
                "language": language,
                "synthetic": True,
                "benchmark_source_id": fixture_id,
                "benchmark_expected_disposition": expected_disposition,
                "cultural_review_required": True,
                "culturally_validated": False,
                "cultural_review_completed": False,
                "cultural_reviewer": "",
                "cultural_review_timestamp": "",
                "cultural_review_notes": "",
                "cultural_review_record_sha256": "",
                "governance_status": "awaiting_nigerian_human_cultural_review",
                "language_governance_version": LANGUAGE_GOVERNANCE_VERSION,
            }
        )
    return staged

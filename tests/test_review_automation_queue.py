from __future__ import annotations

from src.dataset_management import example_sha256
from src.review_automation.config import load_review_config
from src.review_automation.queue import QueueFilters, build_queue


def record(record_id: str, category: str, risk: str, status: str = "draft") -> dict:
    value = {
        "id": record_id,
        "dataset_version": "v0.6",
        "revision": 1,
        "category": category,
        "risk_level": risk,
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": status,
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": f"Unique prompt for {record_id}"},
            {"role": "assistant", "content": f"Unique response for {record_id}."},
        ],
    }
    value["example_sha256"] = example_sha256(value)
    return value


def assessment(record_id: str, score: int, severity: str | None = None) -> dict:
    return {
        "record_id": record_id,
        "overall_score": score,
        "recommended_action": "human_review",
        "findings": (
            [{"check": "fixture", "severity": severity, "message": "Review."}]
            if severity else []
        ),
    }


def test_queue_order_is_deterministic_and_risk_first() -> None:
    rows = [
        record("v06-low", "small_business", "low"),
        record("v06-high", "travel", "high"),
        record("v06-critical", "business_writing", "low"),
    ]
    assessments = [
        assessment("v06-low", 40),
        assessment("v06-high", 90),
        assessment("v06-critical", 95, "critical"),
    ]
    kwargs = {
        "dataset_version": "v0.6",
        "config": load_review_config(),
        "assessments": assessments,
        "generated_at": "2026-07-28T12:00:00+00:00",
    }
    first = build_queue(rows, **kwargs)
    second = build_queue(reversed(rows), **kwargs)
    assert first.to_dict() == second.to_dict()
    assert [item.record_id for item in first.items] == [
        "v06-critical", "v06-high", "v06-low"
    ]


def test_queue_filters_finalized_domain_and_paginates() -> None:
    rows = [
        record("v06-bank", "banking", "medium"),
        record("v06-business", "business_writing", "low"),
        record("v06-approved", "business_writing", "low", "approved"),
    ]
    snapshot = build_queue(
        rows,
        "v0.6",
        load_review_config(),
        filters=QueueFilters(domain_review_required=True),
        page=1,
        page_size=1,
        generated_at="2026-07-28T12:00:00+00:00",
    )
    assert [item.record_id for item in snapshot.items] == ["v06-bank"]
    assert snapshot.excluded_finalized == 1
    assert snapshot.total_matching == 1
    assert snapshot.total_pages == 1
    assert len(snapshot.snapshot_sha256) == 64


def test_queue_training_eligibility_filter() -> None:
    draft = record("v06-draft", "small_business", "low")
    snapshot = build_queue(
        [draft],
        "v0.6",
        load_review_config(),
        filters=QueueFilters(training_eligible=False),
        generated_at="2026-07-28T12:00:00+00:00",
    )
    assert snapshot.items[0].eligibility_reasons
    assert not snapshot.items[0].training_eligible

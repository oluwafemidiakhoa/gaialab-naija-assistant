from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from benchmark_report_all_versions import summarize, write_report  # noqa: E402


def test_summary_aggregates_only_existing_human_scores() -> None:
    records = [
        {
            "model_version": "v0.4",
            "human_review": {"safety": 5, "naturalness": 4, "reviewer": "Ada"},
            "_source_file": "one.jsonl",
        },
        {
            "model_version": "v0.4",
            "human_review": {"safety": None, "naturalness": None, "reviewer": ""},
            "_source_file": "one.jsonl",
        },
        {
            "model_version": "v0.5",
            "safety": 3,
            "_source_file": "two.jsonl",
        },
    ]

    result = summarize(records)

    assert result["model_count"] == 2
    assert result["models"]["v0.4"]["human_reviewed_responses"] == 1
    assert result["models"]["v0.4"]["mean_human_scores"] == {
        "naturalness": 4.0,
        "safety": 5.0,
    }
    assert result["models"]["v0.5"]["mean_human_scores"] == {"safety": 3.0}


def test_report_writes_json_and_markdown(tmp_path: Path) -> None:
    source = tmp_path / "results.jsonl"
    source.write_text(
        json.dumps({"model_id": "model-a", "human_review": {"safety": 4}}) + "\n",
        encoding="utf-8",
    )

    outputs = write_report([source], tmp_path / "reports", "test-report")

    assert outputs["json"].is_file()
    text = outputs["markdown"].read_text(encoding="utf-8")
    assert "model-a" in text
    assert "No scores are assigned automatically" in text
    with pytest.raises(Exception, match="already exists"):
        write_report([source], tmp_path / "reports", "test-report")

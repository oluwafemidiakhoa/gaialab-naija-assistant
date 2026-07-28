from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.dataset_management import example_sha256, import_version
from src.review_automation.config import DEFAULT_CONFIG_PATH, load_review_config
from src.review_automation.queue import build_queue
from src.review_automation.service import (
    analyze_records,
    build_daily_pack,
    write_analysis_run,
    write_daily_pack,
    write_queue_snapshot,
)


def record(record_id="vtest-001") -> dict:
    value = {
        "id": record_id,
        "dataset_version": "vtest",
        "revision": 1,
        "category": "small_business",
        "risk_level": "low",
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": "draft",
        "messages": [
            {"role": "system", "content": "Be safe."},
            {"role": "user", "content": f"Write supplier follow-up {record_id}."},
            {"role": "assistant", "content": "Good day. Please confirm delivery. Thank you."},
        ],
    }
    value["example_sha256"] = example_sha256(value)
    return value


def test_analysis_writes_new_runs_without_changing_status(tmp_path: Path) -> None:
    rows = [record()]
    before = json.dumps(rows, sort_keys=True)
    values, summary = analyze_records(
        rows,
        "vtest",
        load_review_config(),
        generated_at="2026-07-28T12:00:00+00:00",
    )
    first = write_analysis_run(values, summary, tmp_path / "reviews")
    second = write_analysis_run(values, summary, tmp_path / "reviews")
    assert first["recommendations"].is_file()
    assert second["recommendations"].is_file()
    assert first["recommendations"] != second["recommendations"]
    assert summary["official_status_changes"] == 0
    assert not summary["human_approval_assigned"]
    assert json.dumps(rows, sort_keys=True) == before


def test_existing_recommendation_is_skipped_unless_forced() -> None:
    rows = [record()]
    first, _ = analyze_records(
        rows,
        "vtest",
        load_review_config(),
        generated_at="2026-07-28T12:00:00+00:00",
    )
    prior = [first[0].to_dict()]
    skipped, summary = analyze_records(
        rows,
        "vtest",
        load_review_config(),
        prior_recommendations=prior,
        generated_at="2026-07-28T12:01:00+00:00",
    )
    forced, _ = analyze_records(
        rows,
        "vtest",
        load_review_config(),
        prior_recommendations=prior,
        force=True,
        generated_at="2026-07-28T12:01:00+00:00",
    )
    assert skipped == []
    assert summary["skipped_existing_count"] == 1
    assert len(forced) == 1


def test_queue_and_daily_pack_outputs(tmp_path: Path) -> None:
    rows = [record("vtest-001"), record("vtest-002")]
    config = load_review_config()
    snapshot = build_queue(
        rows,
        "vtest",
        config,
        generated_at="2026-07-28T12:00:00+00:00",
    )
    queue_outputs = write_queue_snapshot(snapshot, tmp_path / "queues")
    assert queue_outputs["json"].is_file()
    assert "Advisory prioritization" in queue_outputs["markdown"].read_text(
        encoding="utf-8"
    )
    pack = build_daily_pack(
        rows,
        "vtest",
        config,
        limit=1,
        generated_at="2026-07-28T12:00:00+00:00",
    )
    pack_outputs = write_daily_pack(pack, tmp_path / "packs")
    assert pack["record_count"] == 1
    assert pack["official_status_changes"] == 0
    assert pack_outputs["json"].is_file()
    assert "estimated_review_complexity" in pack["records"][0]


def test_cli_dry_run_never_changes_official_status_or_writes_output(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    registry = tmp_path / "registry"
    import_version(source, registry, "vtest")
    snapshot = registry / "versions" / "vtest" / "records.jsonl"
    before = snapshot.read_bytes()
    output = tmp_path / "must-not-exist"
    command = [
        sys.executable,
        "scripts/review_automation.py",
        "--config",
        str(DEFAULT_CONFIG_PATH),
        "analyze",
        "--version",
        "vtest",
        "--registry",
        str(registry),
        "--releases",
        str(tmp_path / "releases"),
        "--output-dir",
        str(output),
        "--dry-run",
    ]
    completed = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert result["official_status_changes"] == 0
    assert not result["human_approval_assigned"]
    assert result["recommendations"][0]["recommendation"] != "approved"
    assert snapshot.read_bytes() == before
    assert not output.exists()


def test_queue_and_daily_pack_cli_dry_runs_do_not_write(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record()) + "\n", encoding="utf-8")
    registry = tmp_path / "registry"
    import_version(source, registry, "vtest")
    snapshot = registry / "versions" / "vtest" / "records.jsonl"
    before = snapshot.read_bytes()

    for subcommand in ("build-queue", "daily-pack"):
        output = tmp_path / f"{subcommand}-must-not-exist"
        command = [
            sys.executable,
            "scripts/review_automation.py",
            "--config",
            str(DEFAULT_CONFIG_PATH),
            subcommand,
            "--version",
            "vtest",
            "--registry",
            str(registry),
            "--releases",
            str(tmp_path / "releases"),
            "--output-dir",
            str(output),
            "--dry-run",
        ]
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[1],
            check=True,
            capture_output=True,
            text=True,
        )
        result = json.loads(completed.stdout)
        assert result["dry_run"]
        if subcommand == "daily-pack":
            assert result["official_status_changes"] == 0
        assert not output.exists()

    assert snapshot.read_bytes() == before

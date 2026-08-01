from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from pathlib import Path

from scripts.analyze_evaluation_failures import EXPECTED_RESULTS, analyze
from scripts.build_v08_failure_dataset import build
from scripts.validate_v08_failure_dataset import validate
from src.dataset_management import example_sha256, read_jsonl
from src.v08_failure_dataset import (
    BASE_PROHIBITIONS,
    CATEGORIES,
    DATASET_VERSION,
    EXPECTED_PER_CATEGORY,
    EXPECTED_ROLES,
    build_records,
    readiness_diagnostics,
    sender_recipient_reversal,
    unsupported_inferences,
    validate_records,
)


def file_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


def test_exact_record_count_and_category_balance():
    records = build_records()
    assert len(records) == 120
    assert Counter(row["category"] for row in records) == Counter(
        {category: EXPECTED_PER_CATEGORY for category in CATEGORIES}
    )


def test_ids_and_prompts_are_unique():
    records = build_records()
    ids = [row["id"] for row in records]
    prompts = [row["messages"][1]["content"].casefold() for row in records]
    assert len(ids) == len(set(ids))
    assert all(record_id.startswith("v08") for record_id in ids)
    assert len(prompts) == len(set(prompts))


def test_all_records_are_governed_drafts():
    for row in build_records():
        assert row["dataset_version"] == DATASET_VERSION
        assert row["review_status"] == "draft"
        assert row["training_eligible"] is False
        assert row["source"] == "synthetic"
        assert row["source_classification"] == "synthetic"
        assert row["license"] == "CC0-1.0"
        assert row["revision"] == 1
        assert row["created_at"]
        assert row["example_sha256"] == example_sha256(row)
        assert row["human_review"]["final_approval"]["status"] == "pending"


def test_role_metadata_and_state_transitions_are_valid():
    report = validate_records(build_records())
    assert report["valid"], report["errors"]
    for row in build_records():
        state = row["business_state"]
        assert state["sender_role"]
        assert state["recipient_role"]
        assert state["current_state"]
        assert state["requested_action"]
        assert tuple(state["prohibited_inferences"]) == BASE_PROHIBITIONS
        if row["category"] in EXPECTED_ROLES:
            assert not sender_recipient_reversal(row)


def test_unsupported_inference_detection():
    record = deepcopy(build_records()[0])
    record["messages"][2]["content"] += " A late fee will apply."
    findings = unsupported_inferences(record)
    assert {finding["concept"] for finding in findings} == {"late_fee"}


def test_sender_recipient_reversal_detection():
    record = next(
        deepcopy(row) for row in build_records()
        if row["category"] == "invoice_receipt_confirmation_request"
    )
    state = record["business_state"]
    state["sender_role"], state["recipient_role"] = state["recipient_role"], state["sender_role"]
    assert sender_recipient_reversal(record)


def test_pipeline_outputs_are_deterministic_and_never_overwritten(tmp_path):
    first = build(tmp_path)
    before = file_hashes(tmp_path)
    second = build(tmp_path)
    after = file_hashes(tmp_path)
    assert before == after
    assert {item["status"] for item in first["outputs"].values()} == {"created"}
    assert {item["status"] for item in second["outputs"].values()} == {"verified_existing"}
    assert validate(tmp_path / "v0.8_draft.jsonl", prior_paths=())["valid"]


def test_changed_existing_output_is_rejected(tmp_path):
    build(tmp_path)
    manifest = tmp_path / "dataset_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    try:
        build(tmp_path)
    except FileExistsError as exc:
        assert "Refusing to overwrite" in str(exc)
    else:
        raise AssertionError("differing output was silently overwritten")


def test_training_release_is_blocked_for_every_record():
    report = readiness_diagnostics(build_records())
    assert report["training_release_allowed"] is False
    assert report["ready_count"] == 0
    assert report["blocked_count"] == 120
    assert report["blocker_counts"]["not_human_approved"] == 120


def test_evaluation_classifications_are_exact_and_transcripts_not_invented():
    path = Path("evaluation/v0.7.0-rc.3/first_adapter_evaluation.jsonl")
    rows = read_jsonl(path)
    assert {row["evaluation_id"]: row["result"] for row in rows} == EXPECTED_RESULTS
    assert all(row["prompt"] is None and row["model_response"] is None for row in rows)
    report = analyze(path)
    assert report["valid_classifications"] is True
    assert report["transcript_evidence_complete"] is False


def test_prior_release_artifacts_are_immutable_during_build(tmp_path):
    roots = [Path("data/v0.6"), Path("data/releases/v0.6")]
    before = {str(root): file_hashes(root) for root in roots}
    build(tmp_path)
    after = {str(root): file_hashes(root) for root in roots}
    assert before == after


def test_manifest_binds_all_record_hashes(tmp_path):
    build(tmp_path)
    records = read_jsonl(tmp_path / "v0.8_draft.jsonl")
    manifest = json.loads((tmp_path / "dataset_manifest.json").read_text(encoding="utf-8"))
    assert manifest["record_count"] == len(records)
    assert manifest["training_release_allowed"] is False

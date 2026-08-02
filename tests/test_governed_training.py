from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import train_governed_lora
from src.dataset_management import example_sha256, file_sha256
from src.governed_training import (
    DatasetLeakageError,
    DatasetSchemaError,
    GovernanceEvidenceError,
    HardwareError,
    OutputSafetyError,
    assert_release_identity,
    assert_output_isolated,
    build_training_manifest,
    deterministic_order,
    load_jsonl,
    load_yaml_config,
    prepare_output_directory,
    require_execution_hardware,
    tokenize_supervised_record,
    validate_evaluation_bundle,
    validate_training_bundle,
)


def record(
    record_id: str,
    prompt: str,
    *,
    status: str = "approved",
    category: str = "business_writing",
) -> dict:
    value = {
        "id": record_id,
        "dataset_version": "test",
        "revision": 1,
        "category": category,
        "risk_level": "low",
        "messages": [
            {"role": "system", "content": "Be concise."},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": f"Answer for {record_id}."},
        ],
        "source": "synthetic",
        "license": "CC0-1.0",
        "review_status": status,
        "technical_review_completed": True,
    }
    value["example_sha256"] = example_sha256(value)
    return value


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def approved_files(tmp_path: Path) -> tuple[Path, Path]:
    training = tmp_path / "training-input.jsonl"
    validation = tmp_path / "validation-input.jsonl"
    write_jsonl(training, [record("train-1", "Draft an invoice reminder.")])
    write_jsonl(validation, [record("valid-1", "Draft a supplier follow-up.")])
    return training, validation


def candidate_files(tmp_path: Path) -> tuple[Path, Path]:
    training = tmp_path / "training.jsonl"
    validation = tmp_path / "validation.jsonl"
    train_row = record("train-1", "Draft an invoice reminder.", status="draft")
    valid_row = record("valid-1", "Draft a supplier follow-up.", status="draft")
    write_jsonl(training, [train_row])
    write_jsonl(validation, [valid_row])
    eligibility = [
        {
            "record_id": row["id"],
            "record_sha256": row["example_sha256"],
            "release_version": "v0.6",
            "eligible": True,
            "reasons": [],
            "checked_at": "2026-07-30T00:00:00+00:00",
        }
        for row in (train_row, valid_row)
    ]
    for decision in eligibility:
        decision["decision_sha256"] = hashlib.sha256(
            json.dumps(
                decision,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    (tmp_path / "eligibility_report.json").write_text(
        json.dumps(eligibility),
        encoding="utf-8",
    )
    manifest = {
        "release_status": "candidate",
        "dry_run": False,
        "target_version": "v-test-rc1",
        "source_version": "v0.6",
        "splits": {
            "training": {"count": 1, "sha256": file_sha256(training)},
            "validation": {"count": 1, "sha256": file_sha256(validation)},
        },
    }
    (tmp_path / "release_candidate_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return training, validation


def test_schema_validation_and_empty_rejection(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(DatasetSchemaError, match="empty"):
        load_jsonl(empty)

    invalid = record("one", "Hello")
    del invalid["license"]
    write_jsonl(tmp_path / "invalid.jsonl", [invalid])
    with pytest.raises(DatasetSchemaError, match="missing fields: license"):
        load_jsonl(tmp_path / "invalid.jsonl")


def test_duplicate_ids_and_prompts_are_rejected(tmp_path):
    first = record("same", "Please send an invoice.")
    second = record("same", "Different prompt.")
    write_jsonl(tmp_path / "ids.jsonl", [first, second])
    with pytest.raises(DatasetSchemaError, match="duplicate record ID"):
        load_jsonl(tmp_path / "ids.jsonl")

    second = record("different", "PLEASE, send an invoice!")
    write_jsonl(tmp_path / "prompts.jsonl", [first, second])
    with pytest.raises(DatasetSchemaError, match="duplicate normalized prompt"):
        load_jsonl(tmp_path / "prompts.jsonl")


def test_train_validation_leakage_is_rejected(tmp_path):
    training, validation = approved_files(tmp_path)
    write_jsonl(validation, [record("valid-1", "DRAFT, an invoice reminder!")])
    with pytest.raises(DatasetLeakageError, match="normalized prompt"):
        validate_training_bundle(training, validation)


def test_evaluation_cannot_use_a_training_named_file(tmp_path):
    training, _ = approved_files(tmp_path)
    with pytest.raises(DatasetLeakageError, match="evaluation must use"):
        validate_evaluation_bundle(training, training)


def test_candidate_evidence_can_approve_immutable_draft_rows(tmp_path):
    training, validation = candidate_files(tmp_path)
    bundle = validate_training_bundle(training, validation)
    assert bundle.candidate_evidence is not None
    assert bundle.candidate_evidence.candidate_version == "v-test-rc1"


def test_candidate_hash_mismatch_is_rejected(tmp_path):
    training, validation = candidate_files(tmp_path)
    report_path = tmp_path / "eligibility_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report[0]["record_sha256"] = "0" * 64
    decision_hash = {
        key: value for key, value in report[0].items() if key != "decision_sha256"
    }
    report[0]["decision_sha256"] = hashlib.sha256(
        json.dumps(
            decision_hash,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(GovernanceEvidenceError, match="no matching"):
        validate_training_bundle(training, validation)


def test_v08_candidate_requires_authoritative_audit_binding(tmp_path):
    training, validation = candidate_files(tmp_path)
    manifest_path = tmp_path / "release_candidate_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["source_version"] = "v0.8-draft"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(GovernanceEvidenceError, match="human-audit hash and count"):
        validate_training_bundle(training, validation)


def test_release_label_must_match_candidate(tmp_path):
    training, validation = candidate_files(tmp_path)
    evidence = validate_training_bundle(training, validation).candidate_evidence
    assert evidence is not None
    with pytest.raises(GovernanceEvidenceError, match="requires candidate"):
        assert_release_identity("v0.7.0-rc.1", evidence)


def test_unapproved_standalone_record_is_rejected(tmp_path):
    training, validation = approved_files(tmp_path)
    write_jsonl(training, [record("train-1", "One", status="draft")])
    with pytest.raises(GovernanceEvidenceError, match="not approved"):
        validate_training_bundle(training, validation)


def test_deterministic_order_does_not_mutate_input():
    rows = [record(f"id-{index}", f"Prompt {index}") for index in range(8)]
    original = [row["id"] for row in rows]
    first = [row["id"] for row in deterministic_order(rows, 42)]
    second = [row["id"] for row in deterministic_order(rows, 42)]
    assert first == second
    assert [row["id"] for row in rows] == original


class FakeTokenizer:
    pad_token_id = 0

    def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
        if not tokenize:
            return "|".join(message["content"] for message in messages)
        size = 5 if add_generation_prompt else 8
        return list(range(1, size + 1))


def test_supervised_formatting_is_deterministic_and_masks_prompt():
    value = record("id-1", "Prompt")
    first = tokenize_supervised_record(FakeTokenizer(), value, 64)
    second = tokenize_supervised_record(FakeTokenizer(), value, 64)
    assert first == second
    assert first["labels"][:5] == [-100] * 5
    assert first["labels"][5:] == [6, 7, 8]


def test_cpu_refusal_and_validation_only_modes():
    cpu = {"available": False}
    with pytest.raises(HardwareError, match="CUDA GPU required"):
        require_execution_hardware(dry_run=False, smoke_test=False, cuda=cpu)
    assert require_execution_hardware(dry_run=True, smoke_test=False, cuda=cpu) == (
        "cpu_dry_run"
    )
    assert require_execution_hardware(dry_run=False, smoke_test=True, cuda=cpu) == (
        "cpu_smoke_validation_only"
    )


def test_output_overwrite_protection_and_backup(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    (output / "old.txt").write_text("old", encoding="utf-8")
    with pytest.raises(OutputSafetyError, match="not empty"):
        prepare_output_directory(output, overwrite=False, resume_from_checkpoint=None)
    backup = prepare_output_directory(
        output,
        overwrite=True,
        resume_from_checkpoint=None,
        now=lambda: "2026-07-30T00:00:00+00:00",
    )
    assert backup is not None
    assert (backup / "old.txt").read_text(encoding="utf-8") == "old"
    assert output.is_dir()
    assert not any(output.iterdir())


def test_output_cannot_overlap_immutable_inputs(tmp_path):
    training, _ = approved_files(tmp_path / "source")
    with pytest.raises(OutputSafetyError, match="overlaps immutable"):
        assert_output_isolated(training.parent / "generated", (training,))
    with pytest.raises(OutputSafetyError, match="overlaps immutable"):
        assert_output_isolated(tmp_path, (training,))


def test_resume_checkpoint_must_exist_inside_output(tmp_path):
    output = tmp_path / "run"
    output.mkdir()
    outside = tmp_path / "checkpoint-1"
    outside.mkdir()
    with pytest.raises(OutputSafetyError, match="inside the output"):
        prepare_output_directory(
            output,
            overwrite=False,
            resume_from_checkpoint=outside,
        )
    with pytest.raises(OutputSafetyError, match="not found"):
        prepare_output_directory(
            output,
            overwrite=False,
            resume_from_checkpoint=output / "checkpoint-missing",
        )


def test_manifest_contains_governance_and_reproducibility_fields(tmp_path):
    training, validation = approved_files(tmp_path)
    bundle = validate_training_bundle(training, validation)
    manifest = build_training_manifest(
        root=Path.cwd(),
        release_version="v-test",
        base_model="example/model",
        base_model_revision="abc123",
        train_file=training,
        validation_file=validation,
        bundle=bundle,
        resolved_arguments={"seed": 42},
        lora_configuration={"r": 8},
        seed=42,
        status="dry_run_validated",
        cuda={"available": False},
        generated_at="2026-07-30T00:00:00+00:00",
    )
    assert manifest["training_completion_status"] == "dry_run_validated"
    assert manifest["inputs"]["training"]["sha256"] == file_sha256(training)
    assert manifest["governance"]["approved_records_only"] is True
    assert manifest["governance"]["source_records_modified"] is False
    assert manifest["base_model"]["revision"] == "abc123"
    assert manifest["runtime"]["python_version"]
    assert manifest["final_training_loss"] is None


def test_dry_run_writes_manifest_without_importing_training_stack(
    tmp_path, monkeypatch
):
    training, validation = approved_files(tmp_path)
    output = tmp_path.parent / f"{tmp_path.name}-output"
    args = train_governed_lora.parse_args(
        [
            "--train-file",
            str(training),
            "--validation-file",
            str(validation),
            "--output-dir",
            str(output),
            "--dry-run",
        ]
    )
    monkeypatch.setattr(
        train_governed_lora,
        "cuda_information",
        lambda: {"available": False, "devices": []},
    )
    monkeypatch.setattr(
        train_governed_lora,
        "_training_stack",
        lambda *unused: pytest.fail("dry-run must not load or train a model"),
    )
    manifest = train_governed_lora.run(args)
    assert manifest["training_completion_status"] == "dry_run_validated"
    assert (output / "training_manifest.json").is_file()


def test_versioned_configs_preserve_candidate_identity():
    rc1 = load_yaml_config(Path("configs/training/v0.7.0-rc.1.yaml"))
    rc3 = load_yaml_config(Path("configs/training/v0.7.0-rc.3.yaml"))
    assert rc1["release_version"] == "v0.7.0-rc.1"
    assert rc1["dataset"]["train_file"].endswith("v0.7-rc1/training.jsonl")
    assert rc3["release_version"] == "v0.7.0-rc.3"
    assert rc3["dataset"]["train_file"].endswith("v0.7-rc3/training.jsonl")
    assert rc3["model"]["base_model"] == "Qwen/Qwen2.5-0.5B-Instruct"


def test_default_config_uses_latest_eligible_candidate():
    args = train_governed_lora.parse_args(["--dry-run"])
    assert args.release_version == "v0.7.0-rc.3"
    assert args.train_file == Path("data/release_candidates/v0.7-rc3/training.jsonl")

import hashlib
import json
from pathlib import Path

import pytest

from src.dataset_management import file_sha256
from src.model_registry import ModelRegistry, ModelRegistryError


def config(tmp_path: Path):
    script = tmp_path / "train.py"
    script.write_text("print('explicit training only')\n")
    return {
        "training_run_id": "run-001", "dataset_release_version": "v0.6",
        "dataset_manifest_sha256": "a" * 64, "training_data_sha256": "b" * 64,
        "validation_data_sha256": "c" * 64, "benchmark_data_sha256": "d" * 64,
        "git_commit_sha": "e" * 40, "training_script_path": str(script),
        "training_script_sha256": file_sha256(script), "base_model": "Qwen/test",
        "base_model_revision": "fixed", "python_version": "3.11",
        "operating_system": "Windows", "device_type": "cpu", "torch_version": "test",
        "transformers_version": "test", "peft_version": "test", "random_seed": 42,
        "epochs": 1, "learning_rate": 0.0002, "effective_batch_size": 4,
        "max_sequence_length": 512, "lora_configuration": {"r": 8},
        "started_at": "2026-01-01T00:00:00+00:00", "completed_at": "",
        "status": "registered", "training_metrics": {},
    }


def test_run_is_write_once_and_hashed(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    created = registry.register_run(config(tmp_path))
    assert len(created["training_run_sha256"]) == 64
    with pytest.raises(ModelRegistryError, match="overwrite"):
        registry.register_run(config(tmp_path))


def test_altered_script_is_detected(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    values = config(tmp_path)
    registry.register_run(values)
    Path(values["training_script_path"]).write_text("altered\n")
    assert not registry.verify_run("run-001")["verified"]


def test_altered_training_data_is_detected(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    values = config(tmp_path)
    training = tmp_path / "train.jsonl"
    training.write_text('{"id":"one"}\n')
    values["training_data_path"] = str(training)
    values["training_data_sha256"] = file_sha256(training)
    registry.register_run(values)
    training.write_text('{"id":"altered"}\n')
    verification = registry.verify_run("run-001")
    assert not verification["checks"]["training_data_hash_valid"]


def test_artifact_hash_and_alteration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    registry = ModelRegistry(Path("registry"))
    registry.register_run(config(tmp_path))
    output = Path("adapter")
    output.mkdir()
    artifact_file = output / "adapter.bin"
    artifact_file.write_bytes(b"model")
    artifact = registry.register_artifacts("run-001", output)[0]
    assert artifact["file_sha256"] == hashlib.sha256(b"model").hexdigest()
    artifact_file.write_bytes(b"altered")
    assert not registry.verify_run("run-001")["verified"]


def test_release_version_is_write_once(tmp_path):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register_run(config(tmp_path))
    release = registry.create_release("run-001", "v0.6")
    assert release["release_status"] == "candidate"
    with pytest.raises(ModelRegistryError):
        registry.create_release("run-001", "v0.6")

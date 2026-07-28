"""Shared, portable pytest fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from src.dataset_management import file_sha256


@pytest.fixture
def model_run_config() -> Callable[[Path], dict[str, Any]]:
    """Return a factory for a complete, local model-run registry fixture."""

    def build(tmp_path: Path) -> dict[str, Any]:
        script = tmp_path / "train.py"
        script.write_text(
            "print('explicit training only')\n", encoding="utf-8"
        )
        return {
            "training_run_id": "run-001",
            "dataset_release_version": "v0.6",
            "dataset_manifest_sha256": "a" * 64,
            "training_data_sha256": "b" * 64,
            "validation_data_sha256": "c" * 64,
            "benchmark_data_sha256": "d" * 64,
            "git_commit_sha": "e" * 40,
            "training_script_path": str(script),
            "training_script_sha256": file_sha256(script),
            "base_model": "Qwen/test",
            "base_model_revision": "fixed",
            "python_version": "3.11",
            "operating_system": "Windows",
            "device_type": "cpu",
            "torch_version": "test",
            "transformers_version": "test",
            "peft_version": "test",
            "random_seed": 42,
            "epochs": 1,
            "learning_rate": 0.0002,
            "effective_batch_size": 4,
            "max_sequence_length": 512,
            "lora_configuration": {"r": 8},
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "",
            "status": "registered",
            "training_metrics": {},
        }

    return build

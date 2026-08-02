from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import train_governed_lora
from src.governed_training import (
    GovernanceEvidenceError,
    assert_expected_candidate_integrity,
    load_yaml_config,
    validate_candidate_splits,
)


CONFIG_PATH = Path("configs/training/v0.8.0-rc.2.yaml")
CANDIDATE_DIR = Path("data/release_candidates/v0.8-rc2")
NOTEBOOK_PATH = Path("notebooks/gaialab_governed_lora_colab_v08_rc2.ipynb")


def integrity_expectations(config: dict) -> dict:
    return {
        "candidate_version": config["dataset"]["candidate_version"],
        **config["integrity"],
    }


def require_local_candidate() -> None:
    if not CANDIDATE_DIR.is_dir():
        pytest.skip("ignored immutable RC2 candidate is not mounted locally")


def test_rc2_config_has_exact_paths_counts_hashes_and_model() -> None:
    config = load_yaml_config(CONFIG_PATH)

    assert config["release_version"] == "v0.8.0-rc.2"
    assert config["dataset"] == {
        "candidate_version": "v0.8-rc2",
        "train_file": "data/release_candidates/v0.8-rc2/training.jsonl",
        "validation_file": "data/release_candidates/v0.8-rc2/validation.jsonl",
        "held_out_benchmark_file": (
            "data/release_candidates/v0.8-rc2/held_out_benchmark.jsonl"
        ),
        "source_manifest_file": "data/releases/v0.8-draft/dataset_manifest.json",
    }
    assert config["integrity"] == {
        "release_candidate_sha256": (
            "755165026934afc68ade34fd50610016af284cbe2cd769f3b019892e15f3189d"
        ),
        "source_manifest_sha256": (
            "67bd340d2f0400222517b0b86f7f41d91839d23b11f22477e4d24b02983ffd00"
        ),
        "human_audit_sha256": (
            "1c953505356ae8241f588f5b23f5f3ba4487e369584f789ffe26dde9b0bc8b5f"
        ),
        "human_audit_event_count": 248,
        "eligible_count": 80,
        "training_sha256": (
            "92e256eb82a64be41f7d5da6df7dafc360020f7360b386751c8540fdfb927732"
        ),
        "training_count": 68,
        "validation_sha256": (
            "4bdf6777660c61e3e33aad2f83896bacc8d51e567a3fcc47935af39f68d444ec"
        ),
        "validation_count": 6,
        "held_out_benchmark_sha256": (
            "2ecd247a9c8865b76346748f927b21939a81e9c4cc2607d6622570221cdc2748"
        ),
        "held_out_benchmark_count": 6,
    }
    assert config["model"]["base_model"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert config["hub"]["hub_model_id"] == (
        "mgbam/gaialab-naija-assistant-v0.8.0-rc.2-lora"
    )


def test_rc2_config_uses_conservative_colab_lora_defaults() -> None:
    config = load_yaml_config(CONFIG_PATH)
    assert config["training"] == {
        "max_seq_length": 512,
        "epochs": 3.0,
        "max_steps": -1,
        "learning_rate": 0.0002,
        "batch_size": 1,
        "gradient_accumulation_steps": 8,
        "seed": 42,
        "warmup_ratio": 0.1,
        "logging_steps": 1,
        "save_steps": 10,
        "eval_steps": 10,
    }
    assert config["lora"]["lora_r"] == 8
    assert config["lora"]["lora_alpha"] == 16
    assert config["lora"]["lora_dropout"] == 0.05


def test_rc2_candidate_matches_all_trust_anchors_and_has_no_leakage() -> None:
    require_local_candidate()
    config = load_yaml_config(CONFIG_PATH)
    bundle, held_out = validate_candidate_splits(
        CANDIDATE_DIR / "training.jsonl",
        CANDIDATE_DIR / "validation.jsonl",
        CANDIDATE_DIR / "held_out_benchmark.jsonl",
    )
    assert_expected_candidate_integrity(
        bundle=bundle,
        held_out_records=held_out,
        source_manifest_file=Path(config["dataset"]["source_manifest_file"]),
        held_out_benchmark_file=CANDIDATE_DIR / "held_out_benchmark.jsonl",
        expected=integrity_expectations(config),
    )
    assert len(bundle.train_records) == 68
    assert len(bundle.validation_records) == 6
    assert len(held_out) == 6
    split_ids = [
        {record["id"] for record in records}
        for records in (bundle.train_records, bundle.validation_records, held_out)
    ]
    assert split_ids[0].isdisjoint(split_ids[1])
    assert split_ids[0].isdisjoint(split_ids[2])
    assert split_ids[1].isdisjoint(split_ids[2])


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("release_candidate_sha256", "0" * 64),
        ("source_manifest_sha256", "0" * 64),
        ("human_audit_sha256", "0" * 64),
        ("human_audit_event_count", 247),
        ("training_sha256", "0" * 64),
        ("validation_sha256", "0" * 64),
        ("held_out_benchmark_sha256", "0" * 64),
    ],
)
def test_rc2_integrity_mismatch_fails_closed(field: str, bad_value: object) -> None:
    require_local_candidate()
    config = load_yaml_config(CONFIG_PATH)
    bundle, held_out = validate_candidate_splits(
        CANDIDATE_DIR / "training.jsonl",
        CANDIDATE_DIR / "validation.jsonl",
        CANDIDATE_DIR / "held_out_benchmark.jsonl",
    )
    expected = integrity_expectations(config)
    expected[field] = bad_value
    with pytest.raises(GovernanceEvidenceError, match="integrity mismatch"):
        assert_expected_candidate_integrity(
            bundle=bundle,
            held_out_records=held_out,
            source_manifest_file=Path(config["dataset"]["source_manifest_file"]),
            held_out_benchmark_file=CANDIDATE_DIR / "held_out_benchmark.jsonl",
            expected=expected,
        )


def test_rc2_parser_loads_full_candidate_without_enabling_training(tmp_path: Path) -> None:
    args = train_governed_lora.parse_args([
        "--config",
        str(CONFIG_PATH),
        "--output-dir",
        str(tmp_path / "outside-repository-output"),
        "--dry-run",
    ])
    assert args.release_version == "v0.8.0-rc.2"
    assert args.held_out_benchmark_file == CANDIDATE_DIR / "held_out_benchmark.jsonl"
    assert args.source_manifest_file == Path(
        "data/releases/v0.8-draft/dataset_manifest.json"
    )
    assert args.integrity_enabled is True
    assert args.human_audit_event_count == 248
    assert args.push_to_hub is False


def test_rc2_colab_notebook_is_valid_and_fail_closed() -> None:
    notebook = json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert isinstance(notebook["cells"], list) and notebook["cells"]
    source = "\n".join(
        "".join(cell.get("source", [])) for cell in notebook["cells"]
    )
    for required in (
        "RUN_FULL_TRAINING = False",
        "PUSH_TO_HUB = False",
        "EXPECTED_AUDIT_EVENT_COUNT = 248",
        "EXPECTED_AUDIT_SHA256",
        "EXPECTED_SOURCE_MANIFEST_SHA256",
        "EXPECTED_CANDIDATE_SHA256",
        "require_cuda(\"smoke training\")",
        "require_cuda(\"full training\")",
        "predictions.{split_name}.jsonl",
        "validation_metrics.json",
        "held_out_metrics.json",
        'userdata.get("HF_TOKEN")',
        "mgbam/gaialab-naija-assistant-v0.8.0-rc.2-lora",
    ):
        assert required in source
    assert "print(HF_TOKEN" not in source
    assert "training.jsonl\", VALIDATION_FILE" not in source
    for index, cell in enumerate(notebook["cells"]):
        if cell.get("cell_type") == "code":
            compile("".join(cell.get("source", [])), f"notebook-cell-{index}", "exec")


def test_colab_requirements_preserve_preinstalled_pytorch() -> None:
    requirements = Path("requirements-colab.txt").read_text(encoding="utf-8")
    packages = {
        line.split("==", 1)[0].strip().casefold()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert not {"torch", "torchvision", "torchaudio"} & packages
    assert "trl" not in packages
    assert {
        "transformers",
        "peft",
        "accelerate",
        "datasets",
        "huggingface_hub",
        "tokenizers",
        "safetensors",
        "sentencepiece",
        "pyyaml",
        "matplotlib",
    } <= packages


def test_evaluator_writes_split_specific_predictions() -> None:
    source = Path("scripts/evaluate_governed_adapter.py").read_text(encoding="utf-8")
    assert 'f"predictions.{split_name}.jsonl"' in source
    assert '"do_sample": False' in source
    assert '"decoding": "greedy"' in source

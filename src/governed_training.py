"""Safety, validation, formatting, and manifest helpers for governed training."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import random
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml

from src.dataset_management import example_sha256, file_sha256
from src.training_eligibility import DOMAIN_REVIEW_CATEGORIES

REQUIRED_FIELDS = {
    "id",
    "category",
    "risk_level",
    "messages",
    "source",
    "license",
    "example_sha256",
}
EXPECTED_ROLES = ("system", "user", "assistant")
TRAINING_PACKAGES = (
    "torch",
    "transformers",
    "datasets",
    "peft",
    "accelerate",
    "safetensors",
    "huggingface-hub",
    "PyYAML",
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class GovernedTrainingError(ValueError):
    """Base error for a rejected governed training operation."""


class DatasetSchemaError(GovernedTrainingError):
    """The input is not valid governed chat JSONL."""


class GovernanceEvidenceError(GovernedTrainingError):
    """The input is not backed by sufficient human governance evidence."""


class DatasetLeakageError(GovernedTrainingError):
    """Training and evaluation inputs overlap."""


class OutputSafetyError(GovernedTrainingError):
    """An output operation would replace or expose an existing artefact."""


class HardwareError(GovernedTrainingError):
    """The requested execution mode is unsafe on the available hardware."""


@dataclass(frozen=True)
class CandidateEvidence:
    """Verified release-candidate evidence associated with an input split."""

    candidate_version: str
    source_version: str
    manifest_path: str
    manifest_sha256: str
    eligibility_report_path: str
    eligibility_report_sha256: str
    eligible_records: Mapping[str, str]


@dataclass(frozen=True)
class DatasetBundle:
    """Validated training and validation rows plus immutable input evidence."""

    train_records: tuple[dict[str, Any], ...]
    validation_records: tuple[dict[str, Any], ...]
    train_sha256: str
    validation_sha256: str
    candidate_evidence: CandidateEvidence | None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalized_prompt(record: Mapping[str, Any]) -> str:
    """Normalize the user prompt for deterministic duplicate detection."""
    messages = record.get("messages", [])
    user = messages[1].get("content", "") if len(messages) > 1 else ""
    return " ".join(
        "".join(
            character if character.isalnum() else " " for character in user.casefold()
        ).split()
    )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load non-empty JSONL and validate the governed chat schema and hashes."""
    if not path.is_file():
        raise DatasetSchemaError(f"dataset file not found: {path}")

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip():
                continue
            try:
                value = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise DatasetSchemaError(
                    f"{path}:{line_number}: invalid JSON: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise DatasetSchemaError(
                    f"{path}:{line_number}: expected a JSON object"
                )
            validate_record(value, path=path, line_number=line_number)
            records.append(value)

    if not records:
        raise DatasetSchemaError(f"dataset is empty: {path}")
    _assert_unique(records, context=str(path))
    return records


def validate_record(
    record: Mapping[str, Any],
    *,
    path: Path | None = None,
    line_number: int | None = None,
) -> None:
    """Validate one immutable training example without changing it."""
    location = (
        f"{path}:{line_number}"
        if path is not None and line_number is not None
        else "record"
    )
    missing = sorted(field for field in REQUIRED_FIELDS if field not in record)
    if missing:
        raise DatasetSchemaError(f"{location}: missing fields: {', '.join(missing)}")
    for field in ("id", "category", "source", "license", "example_sha256"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise DatasetSchemaError(f"{location}: {field} must be a non-empty string")
    if record.get("risk_level") not in {"low", "medium", "high"}:
        raise DatasetSchemaError(f"{location}: invalid risk_level")

    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) != len(EXPECTED_ROLES):
        raise DatasetSchemaError(
            f"{location}: messages must contain exactly system, user, assistant"
        )
    for message, role in zip(messages, EXPECTED_ROLES):
        if (
            not isinstance(message, dict)
            or message.get("role") != role
            or not isinstance(message.get("content"), str)
            or not message["content"].strip()
        ):
            raise DatasetSchemaError(f"{location}: invalid {role} message")

    expected_hash = example_sha256(dict(record))
    if record["example_sha256"] != expected_hash:
        raise DatasetSchemaError(
            f"{location}: example_sha256 mismatch for {record.get('id', '<unknown>')}"
        )


def _assert_unique(
    records: Sequence[Mapping[str, Any]],
    *,
    context: str,
) -> None:
    seen_ids: dict[str, int] = {}
    seen_prompts: dict[str, int] = {}
    for position, record in enumerate(records, start=1):
        record_id = str(record["id"])
        prompt = normalized_prompt(record)
        if record_id in seen_ids:
            raise DatasetSchemaError(
                f"{context}: duplicate record ID {record_id!r} at records "
                f"{seen_ids[record_id]} and {position}"
            )
        if prompt in seen_prompts:
            raise DatasetSchemaError(
                f"{context}: duplicate normalized prompt at records "
                f"{seen_prompts[prompt]} and {position}"
            )
        seen_ids[record_id] = position
        seen_prompts[prompt] = position


def assert_no_overlap(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    *,
    left_name: str = "training",
    right_name: str = "validation",
) -> None:
    """Reject ID, content-hash, or normalized-prompt overlap."""
    checks: tuple[tuple[str, Callable[[Mapping[str, Any]], str]], ...] = (
        ("record ID", lambda record: str(record["id"])),
        ("record SHA-256", lambda record: str(record["example_sha256"])),
        ("normalized prompt", normalized_prompt),
    )
    for label, key in checks:
        overlap = sorted(
            {key(record) for record in left} & {key(record) for record in right}
        )
        if overlap:
            preview = ", ".join(repr(value) for value in overlap[:3])
            raise DatasetLeakageError(
                f"{left_name}/{right_name} {label} leakage detected: {preview}"
            )


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceEvidenceError(
            f"cannot read governance evidence: {path}"
        ) from exc
    if not isinstance(value, dict):
        raise GovernanceEvidenceError(f"expected JSON object: {path}")
    return value


def candidate_evidence(directory: Path) -> CandidateEvidence | None:
    """Load an immutable candidate manifest and its eligible-record proof."""
    manifest_path = directory / "release_candidate_manifest.json"
    eligibility_path = directory / "eligibility_report.json"
    if not manifest_path.exists() and not eligibility_path.exists():
        return None
    if not manifest_path.is_file() or not eligibility_path.is_file():
        raise GovernanceEvidenceError(
            f"incomplete candidate evidence in {directory}: manifest and eligibility report required"
        )

    manifest = _read_json_object(manifest_path)
    try:
        eligibility = json.loads(eligibility_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GovernanceEvidenceError(
            f"cannot read governance evidence: {eligibility_path}"
        ) from exc
    if manifest.get("release_status") != "candidate" or manifest.get("dry_run") is True:
        raise GovernanceEvidenceError(
            "training inputs must come from a completed candidate"
        )
    recorded_manifest_hash = str(manifest.get("release_candidate_sha256", "")).strip()
    if recorded_manifest_hash:
        manifest_payload = {
            key: value
            for key, value in manifest.items()
            if key != "release_candidate_sha256"
        }
        expected_manifest_hash = hashlib.sha256(
            json.dumps(
                manifest_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if recorded_manifest_hash != expected_manifest_hash:
            raise GovernanceEvidenceError("release candidate manifest SHA-256 mismatch")
    if not isinstance(eligibility, list):
        raise GovernanceEvidenceError(f"expected JSON array: {eligibility_path}")

    eligible_records: dict[str, str] = {}
    for decision in eligibility:
        if not isinstance(decision, dict):
            raise GovernanceEvidenceError("invalid eligibility decision")
        if decision.get("eligible") is not True or decision.get("reasons") not in (
            [],
            None,
        ):
            raise GovernanceEvidenceError(
                "eligibility report contains a non-eligible decision"
            )
        record_id = str(decision.get("record_id", "")).strip()
        record_hash = str(decision.get("record_sha256", "")).strip()
        if not record_id or len(record_hash) != 64:
            raise GovernanceEvidenceError(
                "eligibility decision lacks record ID or SHA-256"
            )
        if decision.get("release_version") != manifest.get("source_version"):
            raise GovernanceEvidenceError(
                f"eligibility decision release mismatch: {record_id}"
            )
        decision_hash = str(decision.get("decision_sha256", "")).strip()
        if len(decision_hash) != 64 or not str(decision.get("checked_at", "")).strip():
            raise GovernanceEvidenceError(
                f"eligibility decision lacks audit hash or timestamp: {record_id}"
            )
        canonical_decision = {
            key: value for key, value in decision.items() if key != "decision_sha256"
        }
        expected_decision_hash = hashlib.sha256(
            json.dumps(
                canonical_decision,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if decision_hash != expected_decision_hash:
            raise GovernanceEvidenceError(
                f"eligibility decision SHA-256 mismatch: {record_id}"
            )
        if record_id in eligible_records:
            raise GovernanceEvidenceError(
                f"duplicate eligibility decision: {record_id}"
            )
        eligible_records[record_id] = record_hash

    if manifest.get("eligible_count") not in (None, len(eligible_records)):
        raise GovernanceEvidenceError(
            "eligible record count does not match candidate manifest"
        )

    return CandidateEvidence(
        candidate_version=str(manifest.get("target_version", "")).strip(),
        source_version=str(manifest.get("source_version", "")).strip(),
        manifest_path=str(manifest_path),
        manifest_sha256=file_sha256(manifest_path),
        eligibility_report_path=str(eligibility_path),
        eligibility_report_sha256=file_sha256(eligibility_path),
        eligible_records=eligible_records,
    )


def _verify_split_manifest(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    manifest_path = path.parent / "release_candidate_manifest.json"
    manifest = _read_json_object(manifest_path)
    split_name = {
        "training.jsonl": "training",
        "validation.jsonl": "validation",
        "held_out_benchmark.jsonl": "held_out_benchmark",
    }.get(path.name)
    if split_name is None:
        raise GovernanceEvidenceError(
            f"candidate split has an unrecognized filename: {path.name}"
        )
    split = manifest.get("splits", {}).get(split_name)
    if not isinstance(split, dict):
        raise GovernanceEvidenceError(f"manifest lacks {split_name} split evidence")
    if split.get("count") != len(records):
        raise GovernanceEvidenceError(
            f"{split_name} record count does not match manifest"
        )
    if split.get("sha256") != file_sha256(path):
        raise GovernanceEvidenceError(f"{split_name} SHA-256 does not match manifest")


def _verify_governance(
    records: Sequence[Mapping[str, Any]],
    evidence: CandidateEvidence | None,
) -> None:
    for record in records:
        record_id = str(record["id"])
        record_hash = str(record["example_sha256"])
        if evidence is not None:
            if evidence.eligible_records.get(record_id) != record_hash:
                raise GovernanceEvidenceError(
                    f"{record_id}: no matching eligible human-governance decision"
                )
            continue

        status = record.get("review_status")
        if status != "approved":
            raise GovernanceEvidenceError(f"{record_id}: review_status is not approved")
        if not (
            record.get("technical_review_completed") or record.get("approved_revision")
        ):
            raise GovernanceEvidenceError(
                f"{record_id}: technical review is incomplete"
            )
        if record.get("category") in DOMAIN_REVIEW_CATEGORIES and not (
            record.get("domain_review_completed")
            or record.get("domain_review_timestamp")
        ):
            raise GovernanceEvidenceError(f"{record_id}: domain review is incomplete")


def validate_training_bundle(train_file: Path, validation_file: Path) -> DatasetBundle:
    """Validate immutable inputs, governance evidence, hashes, and leakage."""
    train_file = train_file.resolve()
    validation_file = validation_file.resolve()
    train_records = load_jsonl(train_file)
    validation_records = load_jsonl(validation_file)
    assert_no_overlap(train_records, validation_records)

    train_evidence = candidate_evidence(train_file.parent)
    validation_evidence = candidate_evidence(validation_file.parent)
    if (train_evidence is None) != (validation_evidence is None):
        raise GovernanceEvidenceError("training and validation evidence types differ")
    evidence = train_evidence
    if evidence is not None:
        if train_file.parent != validation_file.parent:
            raise GovernanceEvidenceError("candidate splits must share one directory")
        if evidence != validation_evidence:
            raise GovernanceEvidenceError("candidate evidence mismatch")
        _verify_split_manifest(train_file, train_records)
        _verify_split_manifest(validation_file, validation_records)

    _verify_governance(train_records, evidence)
    _verify_governance(validation_records, evidence)
    return DatasetBundle(
        train_records=tuple(train_records),
        validation_records=tuple(validation_records),
        train_sha256=file_sha256(train_file),
        validation_sha256=file_sha256(validation_file),
        candidate_evidence=evidence,
    )


def expected_candidate_version(release_version: str) -> str:
    """Map a PEP 440-style prerelease label to the repository candidate label."""
    match = re.fullmatch(r"v(\d+)\.(\d+)\.0-rc\.(\d+)", release_version)
    if match:
        major, minor, candidate = match.groups()
        return f"v{major}.{minor}-rc{candidate}"
    return release_version


def assert_release_identity(
    release_version: str,
    evidence: CandidateEvidence | None,
) -> None:
    """Prevent training one candidate under another release label."""
    if evidence is None:
        return
    expected = expected_candidate_version(release_version)
    if evidence.candidate_version != expected:
        raise GovernanceEvidenceError(
            f"release label {release_version!r} requires candidate {expected!r}, "
            f"not {evidence.candidate_version!r}"
        )


def validate_evaluation_bundle(
    evaluation_file: Path,
    training_file: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], CandidateEvidence | None]:
    """Validate a held-out or validation split and prove no train leakage."""
    if evaluation_file.name not in {"validation.jsonl", "held_out_benchmark.jsonl"}:
        raise DatasetLeakageError(
            "evaluation must use validation.jsonl or held_out_benchmark.jsonl"
        )
    evaluation = load_jsonl(evaluation_file)
    training = load_jsonl(training_file)
    assert_no_overlap(
        training,
        evaluation,
        left_name="training",
        right_name="evaluation",
    )
    train_evidence = candidate_evidence(training_file.resolve().parent)
    eval_evidence = candidate_evidence(evaluation_file.resolve().parent)
    if train_evidence != eval_evidence:
        raise GovernanceEvidenceError("training and evaluation evidence mismatch")
    if train_evidence is not None:
        _verify_split_manifest(training_file.resolve(), training)
        _verify_split_manifest(evaluation_file.resolve(), evaluation)
    _verify_governance(training, train_evidence)
    _verify_governance(evaluation, eval_evidence)
    return evaluation, training, eval_evidence


def format_chat_text(tokenizer: Any, record: Mapping[str, Any]) -> str:
    """Apply the base tokenizer's deterministic chat template."""
    return str(
        tokenizer.apply_chat_template(
            list(record["messages"]),
            tokenize=False,
            add_generation_prompt=False,
        )
    )


def tokenize_supervised_record(
    tokenizer: Any,
    record: Mapping[str, Any],
    max_seq_length: int,
) -> dict[str, list[int]]:
    """Tokenize one chat and mask system/user tokens from the SFT objective."""
    if max_seq_length < 8:
        raise GovernedTrainingError("max_seq_length must be at least 8")
    prompt_messages = list(record["messages"][:-1])
    full_messages = list(record["messages"])
    prompt_ids = list(
        tokenizer.apply_chat_template(
            prompt_messages,
            tokenize=True,
            add_generation_prompt=True,
        )
    )
    full_ids = list(
        tokenizer.apply_chat_template(
            full_messages,
            tokenize=True,
            add_generation_prompt=False,
        )
    )
    full_ids = full_ids[:max_seq_length]
    prompt_length = min(len(prompt_ids), len(full_ids))
    labels = [-100] * prompt_length + full_ids[prompt_length:]
    if not labels or all(label == -100 for label in labels):
        raise DatasetSchemaError(
            f"{record.get('id', '<unknown>')}: assistant response is truncated"
        )
    return {
        "input_ids": full_ids,
        "attention_mask": [1] * len(full_ids),
        "labels": labels,
    }


def deterministic_order(
    records: Iterable[dict[str, Any]],
    seed: int,
) -> list[dict[str, Any]]:
    """Return a reproducible shuffle without mutating the caller's records."""
    ordered = sorted(records, key=lambda record: str(record["id"]))
    random.Random(seed).shuffle(ordered)
    return ordered


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load one strict mapping from a YAML configuration file."""
    if not path.is_file():
        raise GovernedTrainingError(f"configuration file not found: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise GovernedTrainingError(f"invalid configuration: {path}") from exc
    if not isinstance(value, dict):
        raise GovernedTrainingError("training configuration must be a YAML mapping")
    return value


def cuda_information() -> dict[str, Any]:
    """Return non-secret CUDA metadata; import torch only when queried."""
    try:
        import torch
    except ImportError:
        return {
            "available": False,
            "torch_version": None,
            "cuda_version": None,
            "devices": [],
        }
    available = bool(torch.cuda.is_available())
    devices = (
        [
            {
                "index": index,
                "name": torch.cuda.get_device_name(index),
                "capability": list(torch.cuda.get_device_capability(index)),
            }
            for index in range(torch.cuda.device_count())
        ]
        if available
        else []
    )
    return {
        "available": available,
        "torch_version": torch.__version__,
        "cuda_version": torch.version.cuda,
        "devices": devices,
    }


def require_execution_hardware(
    *,
    dry_run: bool,
    smoke_test: bool,
    cuda: Mapping[str, Any] | None = None,
) -> str:
    """Refuse normal CPU training; allow CPU validation-only modes."""
    info = dict(cuda or cuda_information())
    if info.get("available"):
        return "cuda"
    if dry_run:
        return "cpu_dry_run"
    if smoke_test:
        return "cpu_smoke_validation_only"
    raise HardwareError(
        "CUDA GPU required for training; CPU is permitted only for --dry-run "
        "or validation-only --smoke-test"
    )


def assert_output_isolated(output_dir: Path, input_paths: Iterable[Path]) -> None:
    """Reject outputs that could write into, contain, or replace source data."""
    output = output_dir.resolve()
    for input_path in input_paths:
        source_parent = input_path.resolve().parent
        if (
            output == source_parent
            or output.is_relative_to(source_parent)
            or source_parent.is_relative_to(output)
        ):
            raise OutputSafetyError(
                f"output directory overlaps immutable source data: {output}"
            )


def prepare_output_directory(
    output_dir: Path,
    *,
    overwrite: bool,
    resume_from_checkpoint: Path | None,
    now: Callable[[], str] = utc_now,
) -> Path | None:
    """Create an output directory without silently replacing prior artefacts."""
    output_dir = output_dir.resolve()
    if resume_from_checkpoint is not None:
        checkpoint = resume_from_checkpoint.resolve()
        if overwrite:
            raise OutputSafetyError("resume and overwrite are mutually exclusive")
        if not checkpoint.is_dir():
            raise OutputSafetyError(f"resume checkpoint not found: {checkpoint}")
        try:
            checkpoint.relative_to(output_dir)
        except ValueError as exc:
            raise OutputSafetyError(
                "resume checkpoint must be inside the output directory"
            ) from exc
    if output_dir.exists() and not output_dir.is_dir():
        raise OutputSafetyError(f"output path is not a directory: {output_dir}")
    nonempty = output_dir.exists() and any(output_dir.iterdir())
    if nonempty and resume_from_checkpoint is None and not overwrite:
        raise OutputSafetyError(
            f"output directory is not empty: {output_dir}; use resume or explicit overwrite"
        )

    backup: Path | None = None
    if nonempty and overwrite and resume_from_checkpoint is None:
        timestamp = now().replace(":", "").replace("+", "_")
        backup = output_dir.with_name(f"{output_dir.name}.backup.{timestamp}")
        if backup.exists():
            raise OutputSafetyError(f"backup destination already exists: {backup}")
        shutil.move(str(output_dir), str(backup))
    output_dir.mkdir(parents=True, exist_ok=True)
    return backup


def git_metadata(root: Path) -> dict[str, str | None]:
    """Collect repository identity without mutating Git state."""

    def run(*arguments: str) -> str | None:
        try:
            result = subprocess.run(
                ["git", *arguments],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return None
        return result.stdout.strip() or None

    return {
        "commit_sha": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
    }


def dependency_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package in TRAINING_PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    return versions


def build_training_manifest(
    *,
    root: Path,
    release_version: str,
    base_model: str,
    base_model_revision: str | None,
    train_file: Path,
    validation_file: Path,
    bundle: DatasetBundle,
    resolved_arguments: Mapping[str, Any],
    lora_configuration: Mapping[str, Any],
    seed: int,
    status: str,
    cuda: Mapping[str, Any],
    metrics: Mapping[str, Any] | None = None,
    checkpoints: Sequence[str] = (),
    backup_path: Path | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a complete, JSON-serializable audit manifest."""
    candidate = bundle.candidate_evidence
    governance = {
        "approved_records_only": True,
        "source_records_modified": False,
        "candidate_version": candidate.candidate_version if candidate else None,
        "source_version": candidate.source_version if candidate else release_version,
        "candidate_manifest_path": candidate.manifest_path if candidate else None,
        "candidate_manifest_sha256": candidate.manifest_sha256 if candidate else None,
        "eligibility_report_path": candidate.eligibility_report_path
        if candidate
        else None,
        "eligibility_report_sha256": (
            candidate.eligibility_report_sha256 if candidate else None
        ),
    }
    return {
        "schema_version": "1.0",
        "release_version": release_version,
        "generated_at": generated_at or utc_now(),
        "training_completion_status": status,
        "base_model": {
            "model_id": base_model,
            "revision": base_model_revision,
        },
        "repository": git_metadata(root),
        "inputs": {
            "training": {
                "path": str(train_file),
                "sha256": bundle.train_sha256,
                "record_count": len(bundle.train_records),
            },
            "validation": {
                "path": str(validation_file),
                "sha256": bundle.validation_sha256,
                "record_count": len(bundle.validation_records),
            },
        },
        "resolved_arguments": dict(resolved_arguments),
        "lora": dict(lora_configuration),
        "seed": seed,
        "runtime": {
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
        },
        "dependencies": dependency_versions(),
        "hardware": dict(cuda),
        "metrics": dict(metrics or {}),
        "final_training_loss": (metrics or {}).get("train_loss"),
        "final_validation_loss": (metrics or {}).get("eval_loss"),
        "checkpoints": list(checkpoints),
        "previous_output_backup": str(backup_path) if backup_path else None,
        "governance": governance,
    }


def write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    """Write JSON exactly once."""
    if path.exists():
        raise OutputSafetyError(f"refusing to overwrite artefact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def serializable_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Convert argparse/config values to a stable JSON-compatible mapping."""
    return {
        key: str(value) if isinstance(value, Path) else value
        for key, value in sorted(arguments.items())
        if key not in {"hub_token", "token", "hf_token"}
    }


def evidence_as_dict(evidence: CandidateEvidence) -> dict[str, Any]:
    """Expose evidence for tests and human-readable diagnostics."""
    return asdict(evidence)

"""Write-once training-run, model-artifact, and model-release registry."""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from src.dataset_management import DatasetManagementError, atomic_create, file_sha256, utc_now
from src.training_eligibility import canonical_hash

RUN_FIELDS = {
    "training_run_id", "dataset_release_version", "dataset_manifest_sha256",
    "training_data_sha256", "validation_data_sha256", "benchmark_data_sha256",
    "git_commit_sha", "training_script_path", "training_script_sha256",
    "base_model", "base_model_revision", "python_version", "operating_system",
    "device_type", "torch_version", "transformers_version", "peft_version",
    "random_seed", "epochs", "learning_rate", "effective_batch_size",
    "max_sequence_length", "lora_configuration", "started_at", "completed_at",
    "status", "training_metrics",
}
RELEASE_STATUSES = {"candidate", "evaluated", "approved", "published", "deprecated"}


class ModelRegistryError(DatasetManagementError):
    pass


def _write_record(path: Path, data: dict[str, Any], hash_field: str) -> dict[str, Any]:
    payload = dict(data)
    payload[hash_field] = canonical_hash(payload)
    try:
        atomic_create(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    except DatasetManagementError as exc:
        raise ModelRegistryError(str(exc)) from exc
    return payload


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelRegistryError(f"registry record unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ModelRegistryError(f"registry record must be an object: {path}")
    return value


def _valid_hash(record: dict[str, Any], field: str) -> bool:
    payload = {key: value for key, value in record.items() if key != field}
    return record.get(field) == canonical_hash(payload)


class ModelRegistry:
    def __init__(self, root: Path = Path("model_registry")):
        self.root = root

    def run_path(self, run_id: str) -> Path:
        return self.root / "runs" / f"{run_id}.json"

    def release_path(self, version: str) -> Path:
        return self.root / "releases" / f"{version}.json"

    def artifact_path(self, artifact_id: str) -> Path:
        return self.root / "artifacts" / f"{artifact_id}.json"

    def register_run(self, config: dict[str, Any]) -> dict[str, Any]:
        missing = sorted(RUN_FIELDS - config.keys())
        if missing:
            raise ModelRegistryError(f"missing training run fields: {', '.join(missing)}")
        script = Path(config["training_script_path"])
        if not script.is_file() or file_sha256(script) != config["training_script_sha256"]:
            raise ModelRegistryError("training script is missing or its hash does not match")
        return _write_record(
            self.run_path(str(config["training_run_id"])), config, "training_run_sha256"
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        return _read(self.run_path(run_id))

    def register_artifacts(self, run_id: str, output_dir: Path) -> list[dict[str, Any]]:
        self.get_run(run_id)
        if not output_dir.is_dir():
            raise ModelRegistryError(f"artifact directory not found: {output_dir}")
        results = []
        for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
            relative = path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path
            artifact_id = hashlib.sha256(
                f"{run_id}:{relative.as_posix()}".encode()
            ).hexdigest()[:24]
            data = {
                "artifact_id": artifact_id,
                "training_run_id": run_id,
                "artifact_type": path.suffix.lstrip(".") or "file",
                "relative_path": relative.as_posix(),
                "file_size": path.stat().st_size,
                "file_sha256": file_sha256(path),
                "created_at": utc_now(),
            }
            results.append(_write_record(
                self.artifact_path(artifact_id), data, "artifact_sha256"
            ))
        if not results:
            raise ModelRegistryError("no model artifact files found")
        return results

    def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        root = self.root / "artifacts"
        if not root.exists():
            return []
        return sorted(
            (_read(path) for path in root.glob("*.json")),
            key=lambda item: item["artifact_id"],
        )

    def verify_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        checks = {
            "training_run_hash_valid": _valid_hash(run, "training_run_sha256"),
            "training_script_hash_valid": False,
        }
        script = Path(str(run.get("training_script_path", "")))
        checks["training_script_hash_valid"] = (
            script.is_file() and file_sha256(script) == run.get("training_script_sha256")
        )
        for name, hash_field in (
            ("dataset_manifest", "dataset_manifest_sha256"),
            ("training_data", "training_data_sha256"),
            ("validation_data", "validation_data_sha256"),
            ("benchmark_data", "benchmark_data_sha256"),
        ):
            path_value = run.get(f"{name}_path")
            if path_value:
                path = Path(str(path_value))
                checks[f"{name}_hash_valid"] = (
                    path.is_file() and file_sha256(path) == run.get(hash_field)
                )
        for artifact in self.list_artifacts(run_id):
            if artifact["training_run_id"] != run_id:
                continue
            path = Path(artifact["relative_path"])
            checks[f"artifact:{artifact['artifact_id']}"] = (
                _valid_hash(artifact, "artifact_sha256")
                and path.is_file()
                and file_sha256(path) == artifact["file_sha256"]
                and path.stat().st_size == artifact["file_size"]
            )
        return {"training_run_id": run_id, "checks": checks, "verified": all(checks.values())}

    def create_release(
        self, run_id: str, model_version: str, *,
        model_name: str = "GaiaLab Naija Assistant",
        adapter_sha256: str = "", evaluation_report_sha256: str = "",
        release_notes: str = "", release_status: str = "candidate",
    ) -> dict[str, Any]:
        if release_status not in RELEASE_STATUSES:
            raise ModelRegistryError("invalid release status")
        run = self.get_run(run_id)
        data = {
            "model_version": model_version,
            "model_name": model_name,
            "training_run_id": run_id,
            "dataset_release_version": run["dataset_release_version"],
            "dataset_manifest_sha256": run["dataset_manifest_sha256"],
            "base_model": run["base_model"],
            "adapter_sha256": adapter_sha256,
            "evaluation_report_sha256": evaluation_report_sha256,
            "release_notes": release_notes,
            "release_status": release_status,
            "created_at": utc_now(),
            "published_at": "",
        }
        return _write_record(self.release_path(model_version), data, "model_release_sha256")

    def get_release(self, version: str) -> dict[str, Any]:
        return _read(self.release_path(version))


def environment_defaults() -> dict[str, str]:
    return {"python_version": platform.python_version(), "operating_system": platform.system()}

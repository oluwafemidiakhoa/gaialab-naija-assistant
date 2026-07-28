"""Public verification certificates for registered model releases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from src.dataset_management import file_sha256, utc_now
from src.model_registry import ModelRegistry, ModelRegistryError, _valid_hash


def verify_model_release(
    registry: ModelRegistry,
    releases_dir: Path = Path("data/releases"),
    *,
    model_version: str | None = None,
    training_run_id: str | None = None,
    adapter_sha256: str | None = None,
    dataset_manifest_sha256: str | None = None,
    now: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    root = registry.root / "releases"
    if root.exists():
        for path in root.glob("*.json"):
            release = registry.get_release(path.stem)
            if model_version and release.get("model_version") != model_version:
                continue
            if training_run_id and release.get("training_run_id") != training_run_id:
                continue
            if adapter_sha256 and release.get("adapter_sha256") != adapter_sha256:
                continue
            if dataset_manifest_sha256 and release.get("dataset_manifest_sha256") != dataset_manifest_sha256:
                continue
            matches.append(release)
    release = matches[0] if matches else None
    run = None
    checks = {"registry_readable": True}
    if not release and training_run_id:
        try:
            run = registry.get_run(training_run_id)
        except ModelRegistryError:
            run = None
        else:
            checks.update(registry.verify_run(training_run_id)["checks"])
    if release:
        try:
            run = registry.get_run(release["training_run_id"])
        except ModelRegistryError:
            checks["training_run_hash_valid"] = False
        else:
            run_checks = registry.verify_run(run["training_run_id"])["checks"]
            checks.update(run_checks)
            manifest = releases_dir / run["dataset_release_version"] / "dataset_manifest.json"
            checks["dataset_manifest_hash_valid"] = (
                manifest.is_file() and file_sha256(manifest) == run["dataset_manifest_sha256"]
            )
            checks["training_split_hash_valid"] = run_checks.get(
                "training_data_hash_valid", bool(run.get("training_data_sha256"))
            )
            checks["validation_split_hash_valid"] = run_checks.get(
                "validation_data_hash_valid", bool(run.get("validation_data_sha256"))
            )
            artifacts = [
                a for a in registry.list_artifacts(run["training_run_id"])
                if a["training_run_id"] == run["training_run_id"]
            ]
            checks["adapter_files_match_registry"] = (
                bool(artifacts)
                and all(registry.verify_run(run["training_run_id"])["checks"].get(
                    f"artifact:{a['artifact_id']}", False
                ) for a in artifacts)
                and (not release["adapter_sha256"] or release["adapter_sha256"] in {
                    a["file_sha256"] for a in artifacts
                })
            )
            checks["evaluation_report_matches_registry"] = bool(
                release.get("evaluation_report_sha256")
            )
            checks["release_metadata_consistent"] = (
                _valid_hash(release, "model_release_sha256")
                and release["dataset_release_version"] == run["dataset_release_version"]
                and release["dataset_manifest_sha256"] == run["dataset_manifest_sha256"]
            )
    return {
        "certificate_schema": "gaialab.model-verification.v1",
        "model_exists": release is not None,
        "model_version": release.get("model_version") if release else model_version,
        "training_run_exists": run is not None,
        "training_run_id": run.get("training_run_id") if run else training_run_id,
        "dataset_release_version": (
            release.get("dataset_release_version") if release
            else run.get("dataset_release_version") if run else None
        ),
        "dataset_manifest_sha256": (
            release.get("dataset_manifest_sha256") if release
            else run.get("dataset_manifest_sha256") if run else dataset_manifest_sha256
        ),
        "adapter_sha256": release.get("adapter_sha256") if release else adapter_sha256,
        "training_script_sha256": run.get("training_script_sha256") if run else None,
        "git_commit_sha": run.get("git_commit_sha") if run else None,
        "evaluation_report_sha256": release.get("evaluation_report_sha256") if release else None,
        "integrity_checks": checks,
        "integrity_status": (
            "verified" if (release or run) and checks and all(checks.values())
            else "unverified"
        ),
        "generated_at": now(),
    }

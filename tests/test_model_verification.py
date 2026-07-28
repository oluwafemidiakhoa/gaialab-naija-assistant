from src.model_registry import ModelRegistry
from src.model_verification import verify_model_release


def test_unknown_model_is_private_and_unverified(tmp_path):
    certificate = verify_model_release(
        ModelRegistry(tmp_path / "registry"), model_version="unknown",
        now=lambda: "2026-01-01T00:00:00+00:00",
    )
    assert not certificate["model_exists"]
    assert certificate["integrity_status"] == "unverified"
    text = str(certificate)
    assert str(tmp_path) not in text


def test_manifest_mismatch_detected(tmp_path, model_run_config):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register_run(model_run_config(tmp_path))
    registry.create_release("run-001", "v0.6")
    release = tmp_path / "releases" / "v0.6"
    release.mkdir(parents=True)
    (release / "dataset_manifest.json").write_text("{}")
    certificate = verify_model_release(
        registry, tmp_path / "releases", model_version="v0.6"
    )
    assert not certificate["integrity_checks"]["dataset_manifest_hash_valid"]
    assert certificate["integrity_status"] == "unverified"


def test_certificate_has_no_paths_or_environment(tmp_path, model_run_config):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register_run(model_run_config(tmp_path))
    registry.create_release("run-001", "v0.6")
    certificate = verify_model_release(registry, tmp_path, model_version="v0.6")
    assert "training_script_path" not in certificate
    assert "environment" not in certificate


def test_training_run_can_be_verified_before_release(tmp_path, model_run_config):
    registry = ModelRegistry(tmp_path / "registry")
    registry.register_run(model_run_config(tmp_path))
    certificate = verify_model_release(registry, training_run_id="run-001")
    assert certificate["training_run_exists"]
    assert certificate["training_run_id"] == "run-001"
    assert certificate["integrity_status"] == "verified"

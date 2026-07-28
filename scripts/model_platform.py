"""Manage and verify the write-once GaiaLab model registry."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.model_registry import ModelRegistry, ModelRegistryError
from src.model_verification import verify_model_release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("model_registry"))
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register-run")
    register.add_argument("--config", type=Path, required=True)
    artifacts = commands.add_parser("register-artifacts")
    artifacts.add_argument("--run-id", required=True)
    artifacts.add_argument("--output-dir", type=Path, required=True)
    verify_run = commands.add_parser("verify-run")
    verify_run.add_argument("--run-id", required=True)
    create = commands.add_parser("create-release")
    create.add_argument("--run-id", required=True)
    create.add_argument("--model-version", required=True)
    verify = commands.add_parser("verify-release")
    verify.add_argument("--model-version")
    verify.add_argument("--run-id")
    verify.add_argument("--adapter-sha256")
    verify.add_argument("--dataset-manifest-sha256")
    args = parser.parse_args()
    registry = ModelRegistry(args.registry)
    try:
        if args.command == "register-run":
            result = registry.register_run(json.loads(args.config.read_text(encoding="utf-8")))
        elif args.command == "register-artifacts":
            result = registry.register_artifacts(args.run_id, args.output_dir)
        elif args.command == "verify-run":
            result = registry.verify_run(args.run_id)
        elif args.command == "create-release":
            result = registry.create_release(args.run_id, args.model_version)
        else:
            result = verify_model_release(
                registry, model_version=args.model_version,
                training_run_id=args.run_id, adapter_sha256=args.adapter_sha256,
                dataset_manifest_sha256=args.dataset_manifest_sha256,
            )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not isinstance(result, dict) or result.get("integrity_status") != "unverified" else 1
    except (OSError, ValueError, ModelRegistryError) as exc:
        print(f"Model platform failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

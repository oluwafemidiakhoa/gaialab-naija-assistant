"""Manage immutable GaiaLab dataset versions from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dataset_management import (
    DatasetManagementError,
    import_version,
    list_versions,
    publish_version,
    semantic_duplicates,
)
from src.release_verification import (
    ReleaseVerificationError,
    certificate_json,
    verify_release,
)


DEFAULT_REGISTRY = Path("data/registry")
DEFAULT_RELEASES = Path("data/releases")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands = root.add_subparsers(dest="command", required=True)
    add = commands.add_parser("import")
    add.add_argument("--version", required=True)
    add.add_argument("--input", type=Path, required=True)
    commands.add_parser("list")
    duplicates = commands.add_parser("duplicates")
    duplicates.add_argument("--threshold", type=float, default=0.82)
    publish = commands.add_parser("publish")
    publish.add_argument("--version", required=True)
    publish.add_argument("--output-dir", type=Path, default=DEFAULT_RELEASES)
    verify = commands.add_parser("verify")
    verify.add_argument("--version")
    verify.add_argument("--record-id")
    verify.add_argument("--record-sha256")
    verify.add_argument("--manifest-sha256")
    verify.add_argument("--releases-dir", type=Path, default=DEFAULT_RELEASES)
    return root


def main() -> int:
    args = parser().parse_args()
    try:
        if args.command == "import":
            print(import_version(args.input, args.registry, args.version))
        elif args.command == "list":
            print("\n".join(list_versions(args.registry)))
        elif args.command == "duplicates":
            print(json.dumps(semantic_duplicates(args.registry, args.threshold), indent=2))
        elif args.command == "publish":
            outputs = publish_version(args.registry, args.version, args.output_dir)
            print("\n".join(f"{name}: {path}" for name, path in outputs.items()))
        elif args.command == "verify":
            certificate = verify_release(
                args.releases_dir,
                version=args.version,
                record_id=args.record_id,
                record_sha256=args.record_sha256,
                manifest_sha256=args.manifest_sha256,
            )
            print(certificate_json(certificate), end="")
            return 0 if certificate["integrity_status"] in {
                "verified", "superseded"
            } else 1
    except (DatasetManagementError, ReleaseVerificationError, OSError) as exc:
        print(f"Dataset platform failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

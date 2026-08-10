"""Create and verify externally portable GaiaLab operator-chain checkpoints."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.operator_action_log import NeonOperatorActionLog, OperatorActionLog
from src.operator_checkpoint import create_checkpoint, verify_checkpoint, verify_checkpoint_against_log
from src.storage_backend import operator_neon_backend


def _action_log():
    backend = operator_neon_backend()
    if backend is not None:
        return NeonOperatorActionLog(backend)
    path = os.getenv("GAIALAB_OPERATOR_ACTION_DB")
    if not path:
        operator_db = os.getenv("GAIALAB_OPERATOR_DB")
        if operator_db:
            path = operator_db + ".actions.sqlite3"
    if not path:
        raise SystemExit("operator action log is not configured")
    return OperatorActionLog(path)


def _read(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or verify signed operator-action checkpoints")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--output", required=True)
    create.add_argument("--stream-id", default="global")

    verify = sub.add_parser("verify")
    verify.add_argument("--file", required=True)
    verify.add_argument("--expected-key-id")

    current = sub.add_parser("verify-current")
    current.add_argument("--file", required=True)
    current.add_argument("--expected-key-id")

    args = parser.parse_args()
    if args.command == "create":
        private_key = os.getenv("GAIALAB_OPERATOR_CHECKPOINT_SIGNING_KEY_B64")
        if not private_key:
            raise SystemExit("GAIALAB_OPERATOR_CHECKPOINT_SIGNING_KEY_B64 is required to create a checkpoint")
        package = create_checkpoint(_action_log(), private_key, stream_id=args.stream_id)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = {
            "created": True,
            "path": str(output),
            "checkpoint_id": package["checkpoint"]["checkpoint_id"],
            "key_id": package["signature"]["key_id"],
            "action_count": package["checkpoint"]["action_count"],
            "action_head_sha256": package["checkpoint"]["action_head_sha256"],
        }
    elif args.command == "verify":
        result = verify_checkpoint(_read(args.file), expected_key_id=args.expected_key_id)
    elif args.command == "verify-current":
        result = verify_checkpoint_against_log(
            _read(args.file), _action_log(), expected_key_id=args.expected_key_id
        )
    else:  # pragma: no cover
        raise SystemExit("unsupported command")

    print(json.dumps(result, indent=2, sort_keys=True))
    if not result.get("valid", result.get("created", False)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

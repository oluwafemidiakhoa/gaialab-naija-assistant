"""Create, append, and verify portable operator-checkpoint transparency records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.checkpoint_transparency import (
    append_transparency_record,
    create_transparency_record,
    verify_transparency_log,
    verify_transparency_record,
)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _trusted(values: list[str] | None) -> set[str] | None:
    if not values:
        return None
    return {value.strip() for value in values if value.strip()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    record = commands.add_parser("record")
    record.add_argument("--checkpoint", type=Path, required=True)
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--trusted-key-id", action="append")

    verify_record = commands.add_parser("verify-record")
    verify_record.add_argument("--file", type=Path, required=True)
    verify_record.add_argument("--trusted-key-id", action="append")

    append = commands.add_parser("append")
    append.add_argument("--record", type=Path, required=True)
    append.add_argument("--ledger", type=Path, required=True)
    append.add_argument("--trusted-key-id", action="append")

    verify_log = commands.add_parser("verify-log")
    verify_log.add_argument("--ledger", type=Path, required=True)
    verify_log.add_argument("--trusted-key-id", action="append")
    verify_log.add_argument("--expected-head-sha256")

    args = parser.parse_args()
    trusted = _trusted(getattr(args, "trusted_key_id", None))
    try:
        if args.command == "record":
            value = create_transparency_record(
                _read(args.checkpoint),
                trusted_key_ids=trusted,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            if args.output.exists():
                raise FileExistsError(f"refusing to overwrite: {args.output}")
            args.output.write_text(
                json.dumps(value, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = {
                "created": True,
                "path": str(args.output),
                "publication_id": value["publication_id"],
                "checkpoint_id": value["checkpoint"]["checkpoint_id"],
                "key_id": value["signature"]["key_id"],
                "checkpoint_package_sha256": value["checkpoint_package_sha256"],
            }
        elif args.command == "verify-record":
            result = verify_transparency_record(_read(args.file), trusted_key_ids=trusted)
        elif args.command == "append":
            result = append_transparency_record(
                args.ledger,
                _read(args.record),
                trusted_key_ids=trusted,
            )
        elif args.command == "verify-log":
            result = verify_transparency_log(
                args.ledger,
                trusted_key_ids=trusted,
                expected_head_sha256=args.expected_head_sha256,
            )
        else:  # pragma: no cover
            raise AssertionError("unknown command")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2, sort_keys=True))
        return 1

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid", result.get("created", result.get("published", False))) else 1


if __name__ == "__main__":
    raise SystemExit(main())

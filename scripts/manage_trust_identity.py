"""Operator CLI for GaiaLab tenant, policy, API-key, and signing-key lifecycle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.key_registry import SigningKeyRegistry
from src.tenant_auth import TenantRegistry
from src.tenant_policy import TenantPolicyStore


def _read_policy(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage GaiaLab Trust Rail identity and policy registries")
    sub = parser.add_subparsers(dest="command", required=True)

    create_tenant = sub.add_parser("create-tenant")
    create_tenant.add_argument("--db", required=True)
    create_tenant.add_argument("--name", required=True)
    create_tenant.add_argument("--tenant-id")

    issue_key = sub.add_parser("issue-api-key")
    issue_key.add_argument("--db", required=True)
    issue_key.add_argument("--tenant-id", required=True)
    issue_key.add_argument("--label")
    issue_key.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        choices=["verification:write", "receipts:read", "audit:export"],
        help="Repeat to grant multiple scopes. Defaults to verification:write + receipts:read.",
    )
    issue_key.add_argument("--rate-limit-per-minute", type=int, default=120)

    disable_key = sub.add_parser("disable-api-key")
    disable_key.add_argument("--db", required=True)
    disable_key.add_argument("--key-id", required=True)

    create_policy = sub.add_parser("create-policy")
    create_policy.add_argument("--db", required=True)
    create_policy.add_argument("--tenant-id", required=True)
    create_policy.add_argument("--file", required=True)
    create_policy.add_argument("--no-activate", action="store_true")
    create_policy.add_argument("--note")

    activate_policy = sub.add_parser("activate-policy")
    activate_policy.add_argument("--db", required=True)
    activate_policy.add_argument("--tenant-id", required=True)
    activate_policy.add_argument("--policy-id", required=True)
    activate_policy.add_argument("--note")

    list_policies = sub.add_parser("list-policies")
    list_policies.add_argument("--db", required=True)
    list_policies.add_argument("--tenant-id", required=True)

    register_signing = sub.add_parser("register-signing-key")
    register_signing.add_argument("--db", required=True)
    register_signing.add_argument("--public-key-b64", required=True)
    register_signing.add_argument("--label")

    transition_signing = sub.add_parser("transition-signing-key")
    transition_signing.add_argument("--db", required=True)
    transition_signing.add_argument("--key-id", required=True)
    transition_signing.add_argument("--event", choices=["activated", "retired", "revoked"], required=True)
    transition_signing.add_argument("--reason")

    list_signing = sub.add_parser("list-signing-keys")
    list_signing.add_argument("--db", required=True)

    args = parser.parse_args()

    if args.command == "create-tenant":
        result = TenantRegistry(args.db).create_tenant(args.name, tenant_id=args.tenant_id)
    elif args.command == "issue-api-key":
        result = TenantRegistry(args.db).issue_api_key(
            args.tenant_id,
            label=args.label,
            scopes=args.scopes,
            rate_limit_per_minute=args.rate_limit_per_minute,
        )
    elif args.command == "disable-api-key":
        TenantRegistry(args.db).disable_api_key(args.key_id)
        result = {"disabled": True, "key_id": args.key_id}
    elif args.command == "create-policy":
        result = TenantPolicyStore(args.db).create_version(
            args.tenant_id,
            _read_policy(args.file),
            activate=not args.no_activate,
            note=args.note,
        )
    elif args.command == "activate-policy":
        result = TenantPolicyStore(args.db).activate(
            args.tenant_id,
            args.policy_id,
            note=args.note,
        )
    elif args.command == "list-policies":
        store = TenantPolicyStore(args.db)
        result = {
            "active": store.active_for(args.tenant_id),
            "versions": store.list_versions(args.tenant_id),
        }
    elif args.command == "register-signing-key":
        result = SigningKeyRegistry(args.db).register(args.public_key_b64, label=args.label)
    elif args.command == "transition-signing-key":
        result = SigningKeyRegistry(args.db).transition(args.key_id, args.event, reason=args.reason)
    elif args.command == "list-signing-keys":
        result = {"keys": SigningKeyRegistry(args.db).list()}
    else:  # pragma: no cover
        raise SystemExit("unsupported command")

    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

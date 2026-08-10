"""Manage GaiaLab Trust Rail identities and policy on Neon Postgres."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.neon_storage import (
    NeonBackend,
    NeonOperatorRegistry,
    NeonSigningKeyRegistry,
    NeonTenantPolicyStore,
    NeonTenantRegistry,
)


def _backend() -> NeonBackend:
    migration_url = os.getenv("GAIALAB_MIGRATION_DATABASE_URL")
    if not migration_url:
        raise SystemExit("GAIALAB_MIGRATION_DATABASE_URL is required for provisioning")
    return NeonBackend(migration_url, migration_database_url=migration_url)


def _read_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage GaiaLab Trust Rail on Neon")
    sub = parser.add_subparsers(dest="command", required=True)

    create_tenant = sub.add_parser("create-tenant")
    create_tenant.add_argument("--name", required=True)
    create_tenant.add_argument("--tenant-id")

    issue_tenant_key = sub.add_parser("issue-api-key")
    issue_tenant_key.add_argument("--tenant-id", required=True)
    issue_tenant_key.add_argument("--label")
    issue_tenant_key.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        choices=["verification:write", "receipts:read", "audit:export"],
    )
    issue_tenant_key.add_argument("--rate-limit-per-minute", type=int, default=120)

    disable_tenant_key = sub.add_parser("disable-api-key")
    disable_tenant_key.add_argument("--key-id", required=True)

    create_operator = sub.add_parser("create-operator")
    create_operator.add_argument("--name", required=True)
    create_operator.add_argument("--operator-id")

    issue_admin_key = sub.add_parser("issue-admin-key")
    issue_admin_key.add_argument("--operator-id", required=True)
    issue_admin_key.add_argument("--label")
    issue_admin_key.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        choices=["audit:lifecycle", "audit:delete", "tenants:manage", "policies:manage", "signing-keys:manage"],
    )

    disable_admin_key = sub.add_parser("disable-admin-key")
    disable_admin_key.add_argument("--key-id", required=True)

    create_policy = sub.add_parser("create-policy")
    create_policy.add_argument("--tenant-id", required=True)
    create_policy.add_argument("--file", required=True)
    create_policy.add_argument("--no-activate", action="store_true")
    create_policy.add_argument("--note")

    activate_policy = sub.add_parser("activate-policy")
    activate_policy.add_argument("--tenant-id", required=True)
    activate_policy.add_argument("--policy-id", required=True)
    activate_policy.add_argument("--note")

    list_policies = sub.add_parser("list-policies")
    list_policies.add_argument("--tenant-id", required=True)

    register_signing = sub.add_parser("register-signing-key")
    register_signing.add_argument("--public-key-b64", required=True)
    register_signing.add_argument("--label")

    transition_signing = sub.add_parser("transition-signing-key")
    transition_signing.add_argument("--key-id", required=True)
    transition_signing.add_argument("--event", choices=["activated", "retired", "revoked"], required=True)
    transition_signing.add_argument("--reason")

    list_signing = sub.add_parser("list-signing-keys")

    args = parser.parse_args()
    backend = _backend()

    if args.command == "create-tenant":
        result = NeonTenantRegistry(backend).create_tenant(args.name, tenant_id=args.tenant_id)
    elif args.command == "issue-api-key":
        result = NeonTenantRegistry(backend).issue_api_key(
            args.tenant_id,
            label=args.label,
            scopes=args.scopes,
            rate_limit_per_minute=args.rate_limit_per_minute,
        )
    elif args.command == "disable-api-key":
        NeonTenantRegistry(backend).disable_api_key(args.key_id)
        result = {"disabled": True, "key_id": args.key_id}
    elif args.command == "create-operator":
        result = NeonOperatorRegistry(backend).create_operator(args.name, operator_id=args.operator_id)
    elif args.command == "issue-admin-key":
        result = NeonOperatorRegistry(backend).issue_admin_key(
            args.operator_id,
            label=args.label,
            scopes=args.scopes,
        )
    elif args.command == "disable-admin-key":
        NeonOperatorRegistry(backend).disable_admin_key(args.key_id)
        result = {"disabled": True, "key_id": args.key_id}
    elif args.command == "create-policy":
        result = NeonTenantPolicyStore(backend).create_version(
            args.tenant_id,
            _read_json(args.file),
            activate=not args.no_activate,
            note=args.note,
        )
    elif args.command == "activate-policy":
        result = NeonTenantPolicyStore(backend).activate(
            args.tenant_id,
            args.policy_id,
            note=args.note,
        )
    elif args.command == "list-policies":
        store = NeonTenantPolicyStore(backend)
        result = {"active": store.active_for(args.tenant_id), "versions": store.list_versions(args.tenant_id)}
    elif args.command == "register-signing-key":
        result = NeonSigningKeyRegistry(backend).register(args.public_key_b64, label=args.label)
    elif args.command == "transition-signing-key":
        result = NeonSigningKeyRegistry(backend).transition(args.key_id, args.event, reason=args.reason)
    elif args.command == "list-signing-keys":
        result = {"keys": NeonSigningKeyRegistry(backend).list()}
    else:  # pragma: no cover
        raise SystemExit("unsupported command")

    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
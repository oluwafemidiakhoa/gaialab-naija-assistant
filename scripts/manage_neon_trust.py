"""Manage GaiaLab Trust Rail identities and policy on Neon Postgres."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from src.neon_storage import NeonBackend, NeonOperatorRegistry, NeonSigningKeyRegistry, NeonTenantPolicyStore, NeonTenantRegistry
from src.operator_action_log import NeonOperatorActionLog


MUTATING_COMMANDS = {
    "create-tenant", "issue-api-key", "disable-api-key", "create-operator",
    "issue-admin-key", "disable-admin-key", "create-policy", "activate-policy",
    "register-signing-key", "transition-signing-key",
}


def _backend() -> NeonBackend:
    migration_url = os.getenv("GAIALAB_MIGRATION_DATABASE_URL")
    if not migration_url: raise SystemExit("GAIALAB_MIGRATION_DATABASE_URL is required for provisioning")
    return NeonBackend(migration_url, migration_database_url=migration_url)


def _read_json(path: str) -> dict: return json.loads(Path(path).read_text(encoding="utf-8"))


def _audit_success(backend: NeonBackend, *, actor_id: str, command: str, target_type: str, target_id: str, metadata=None) -> None:
    NeonOperatorActionLog(backend).append(
        operator_id=actor_id,
        key_id=None,
        action_type=f"provisioning.{command}.completed",
        target_type=target_type,
        target_id=target_id,
        metadata=dict(metadata or {}),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage GaiaLab Trust Rail on Neon")
    parser.add_argument(
        "--actor-id",
        default=os.getenv("GAIALAB_PROVISIONING_ACTOR_ID"),
        help="Human/operator identifier recorded in the tamper-evident admin action log",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    create_tenant = sub.add_parser("create-tenant"); create_tenant.add_argument("--name", required=True); create_tenant.add_argument("--tenant-id")
    issue_tenant_key = sub.add_parser("issue-api-key"); issue_tenant_key.add_argument("--tenant-id", required=True); issue_tenant_key.add_argument("--label")
    issue_tenant_key.add_argument("--scope", action="append", dest="scopes", choices=["verification:write", "receipts:read", "audit:export"])
    issue_tenant_key.add_argument("--rate-limit-per-minute", type=int, default=120)
    disable_tenant_key = sub.add_parser("disable-api-key"); disable_tenant_key.add_argument("--key-id", required=True)
    create_operator = sub.add_parser("create-operator"); create_operator.add_argument("--name", required=True); create_operator.add_argument("--operator-id")
    issue_admin_key = sub.add_parser("issue-admin-key"); issue_admin_key.add_argument("--operator-id", required=True); issue_admin_key.add_argument("--label")
    issue_admin_key.add_argument("--scope", action="append", dest="scopes", choices=["audit:lifecycle", "audit:delete", "dashboard:read", "tenants:manage", "policies:manage", "signing-keys:manage"])
    disable_admin_key = sub.add_parser("disable-admin-key"); disable_admin_key.add_argument("--key-id", required=True)
    create_policy = sub.add_parser("create-policy"); create_policy.add_argument("--tenant-id", required=True); create_policy.add_argument("--file", required=True); create_policy.add_argument("--no-activate", action="store_true"); create_policy.add_argument("--note")
    activate_policy = sub.add_parser("activate-policy"); activate_policy.add_argument("--tenant-id", required=True); activate_policy.add_argument("--policy-id", required=True); activate_policy.add_argument("--note")
    list_policies = sub.add_parser("list-policies"); list_policies.add_argument("--tenant-id", required=True)
    register_signing = sub.add_parser("register-signing-key"); register_signing.add_argument("--public-key-b64", required=True); register_signing.add_argument("--label")
    transition_signing = sub.add_parser("transition-signing-key"); transition_signing.add_argument("--key-id", required=True); transition_signing.add_argument("--event", choices=["activated", "retired", "revoked"], required=True); transition_signing.add_argument("--reason")
    sub.add_parser("list-signing-keys")
    list_actions = sub.add_parser("list-operator-actions"); list_actions.add_argument("--limit", type=int, default=100)
    sub.add_parser("verify-operator-actions")

    args = parser.parse_args()
    if args.command in MUTATING_COMMANDS and not args.actor_id:
        raise SystemExit("--actor-id or GAIALAB_PROVISIONING_ACTOR_ID is required for mutating provisioning commands")
    backend = _backend(); audit = None

    if args.command == "create-tenant":
        result = NeonTenantRegistry(backend).create_tenant(args.name, tenant_id=args.tenant_id)
        audit = ("tenant", result["tenant_id"], {})
    elif args.command == "issue-api-key":
        result = NeonTenantRegistry(backend).issue_api_key(args.tenant_id, label=args.label, scopes=args.scopes, rate_limit_per_minute=args.rate_limit_per_minute)
        audit = ("tenant_api_key", result["key_id"], {"scopes": result["scopes"], "rate_limit_per_minute": result["rate_limit_per_minute"]})
    elif args.command == "disable-api-key":
        NeonTenantRegistry(backend).disable_api_key(args.key_id); result = {"disabled": True, "key_id": args.key_id}; audit = ("tenant_api_key", args.key_id, {"disabled": True})
    elif args.command == "create-operator":
        result = NeonOperatorRegistry(backend).create_operator(args.name, operator_id=args.operator_id); audit = ("operator", result["operator_id"], {})
    elif args.command == "issue-admin-key":
        result = NeonOperatorRegistry(backend).issue_admin_key(args.operator_id, label=args.label, scopes=args.scopes); audit = ("operator_api_key", result["key_id"], {"scopes": result["scopes"]})
    elif args.command == "disable-admin-key":
        NeonOperatorRegistry(backend).disable_admin_key(args.key_id); result = {"disabled": True, "key_id": args.key_id}; audit = ("operator_api_key", args.key_id, {"disabled": True})
    elif args.command == "create-policy":
        result = NeonTenantPolicyStore(backend).create_version(args.tenant_id, _read_json(args.file), activate=not args.no_activate, note=args.note)
        audit = ("tenant_policy", result["policy_id"], {"tenant_id_sha256": __import__("hashlib").sha256(args.tenant_id.encode()).hexdigest(), "activated": not args.no_activate})
    elif args.command == "activate-policy":
        result = NeonTenantPolicyStore(backend).activate(args.tenant_id, args.policy_id, note=args.note); audit = ("tenant_policy", args.policy_id, {"activated": True})
    elif args.command == "list-policies":
        store = NeonTenantPolicyStore(backend); result = {"active": store.active_for(args.tenant_id), "versions": store.list_versions(args.tenant_id)}
    elif args.command == "register-signing-key":
        result = NeonSigningKeyRegistry(backend).register(args.public_key_b64, label=args.label); audit = ("signing_key", result["key_id"], {"status": result["status"]})
    elif args.command == "transition-signing-key":
        result = NeonSigningKeyRegistry(backend).transition(args.key_id, args.event, reason=args.reason); audit = ("signing_key", args.key_id, {"event": args.event, "status": result["status"]})
    elif args.command == "list-signing-keys":
        result = {"keys": NeonSigningKeyRegistry(backend).list()}
    elif args.command == "list-operator-actions":
        result = {"actions": NeonOperatorActionLog(backend).list(limit=args.limit)}
    elif args.command == "verify-operator-actions":
        result = NeonOperatorActionLog(backend).verify_chain()
    else: raise SystemExit("unsupported command")

    if audit is not None:
        target_type, target_id, metadata = audit
        _audit_success(backend, actor_id=args.actor_id, command=args.command, target_type=target_type, target_id=target_id, metadata=metadata)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__": main()

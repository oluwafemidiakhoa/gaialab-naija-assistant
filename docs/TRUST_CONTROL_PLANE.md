# GaiaLab Naija Trust Control Plane

This layer adds organization-specific policy, API-key scopes, and deterministic rate limits on top of the global Trust Rail.

## Principle

Tenant policy may make a global verification result stricter. It must never weaken a global safety result. A global `BLOCK` remains `BLOCK` even if the tenant policy would otherwise allow the interaction.

## API-key scopes

Supported scopes:

- `verification:write` — submit candidate AI responses to `POST /v1/verify`
- `receipts:read` — retrieve and verify stored tenant receipts
- `audit:export` — reserved for the audit-export slice

API keys are stored only as SHA-256 hashes. Each key also has a per-minute request limit.

Create a scoped key:

```bash
python scripts/manage_trust_identity.py issue-api-key \
  --db data/trust_tenants.sqlite3 \
  --tenant-id TENANT_ID \
  --scope verification:write \
  --scope receipts:read \
  --rate-limit-per-minute 60
```

## Immutable tenant policies

Tenant policy versions are immutable. Activations are append-only events, so an audit can reconstruct which policy was active when a receipt was issued.

Example policy:

```json
{
  "name": "example-fintech-strict-v1",
  "max_automated_risk": 20,
  "require_human_review_above_ngn": 500000,
  "block_finding_codes": [
    "TRANSACTION_STATE_CONTRADICTION",
    "UNSUPPORTED_ACCOUNT_ACTION"
  ],
  "escalate_finding_codes": [
    "UNSUPPORTED_REFUND_OR_REVERSAL",
    "UNSUPPORTED_TIMELINE"
  ],
  "require_signed_receipts": true,
  "require_persisted_receipts": true
}
```

Create and activate it:

```bash
python scripts/manage_trust_identity.py create-policy \
  --db data/trust_policies.sqlite3 \
  --tenant-id TENANT_ID \
  --file config/trust_policies/example_fintech_strict.json \
  --note "initial production policy"
```

List policy history:

```bash
python scripts/manage_trust_identity.py list-policies \
  --db data/trust_policies.sqlite3 \
  --tenant-id TENANT_ID
```

## Runtime policy controls

The first policy schema supports:

- maximum automated risk score before escalation
- mandatory human review above a configured NGN transaction amount
- finding codes that force `ESCALATE`
- finding codes that force `BLOCK`
- mandatory signed receipts
- mandatory persisted receipts

The receipt records the active `tenant_policy_id`, policy hash, and deterministic policy-evaluation ID.

## Fail-closed guarantees

If a tenant requires signed receipts but no signing key is configured, verification fails instead of silently issuing an unsigned result.

If a tenant requires persisted receipts but no receipt store is configured, verification also fails instead of silently losing the audit record.

## Rate limiting

The MVP uses an SQLite fixed-window limiter keyed by API-key ID. Configure an explicit database with:

```bash
export GAIALAB_RATE_LIMIT_DB="data/trust_rate_limits.sqlite3"
```

If omitted, the service derives a sidecar rate-limit database from `GAIALAB_TENANT_DB`.

SQLite is appropriate for local and single-node MVP deployment. A horizontally scaled production service should move rate counters to a shared atomic backend.

## Environment

```text
GAIALAB_TENANT_DB
GAIALAB_TENANT_POLICY_DB
GAIALAB_RATE_LIMIT_DB
GAIALAB_TRUST_SIGNING_KEY_B64
GAIALAB_TRUST_KEY_REGISTRY_DB
GAIALAB_TRUST_RECEIPT_DB
```

## Security boundaries

- Tenant policy is not human approval.
- Extracted claims are not evidence.
- A signed receipt proves receipt integrity/authenticity, not truth of upstream data.
- Public signing-key discovery does not expose private signing material.
- Tenant receipt storage remains tenant-scoped.
- Policy activation and signing-key lifecycle history remain append-only.

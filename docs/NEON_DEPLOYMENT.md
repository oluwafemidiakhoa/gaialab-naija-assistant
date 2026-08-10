# GaiaLab Trust Rail on Neon Postgres

Neon Postgres is the production persistence target for the GaiaLab Naija Trust Rail. SQLite remains supported for local development and isolated tests.

## Storage selection

The API automatically selects Neon when this variable is present:

```bash
export GAIALAB_DATABASE_URL="postgresql://..."
```

Use the **pooled** Neon connection string for `GAIALAB_DATABASE_URL`. It is used by normal API traffic for tenant authentication, operator authentication, policies, rate limiting, receipts, signing-key lifecycle, audit exports, and audit lifecycle events.

For schema initialization, prefer a **direct** Neon connection string:

```bash
export GAIALAB_MIGRATION_DATABASE_URL="postgresql://..."
```

If `GAIALAB_MIGRATION_DATABASE_URL` is omitted, initialization falls back to `GAIALAB_DATABASE_URL`.

Private database URLs are secrets and must never be committed to the repository.

## Initialize schema

Install dependencies and run:

```bash
python scripts/init_neon_storage.py
```

The bootstrap is idempotent and creates the Trust Rail tables and indexes using `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`.

Current shared tables include:

- `tenants`
- `tenant_api_keys`
- `operators`
- `operator_api_keys`
- `signing_keys`
- `signing_key_events`
- `tenant_policy_versions`
- `tenant_policy_events`
- `verification_receipts`
- `api_rate_windows`
- `audit_exports`
- `audit_export_events`

## Provision a tenant

```bash
python scripts/manage_neon_trust.py create-tenant \
  --name "Example Fintech"
```

Issue a verification key:

```bash
python scripts/manage_neon_trust.py issue-api-key \
  --tenant-id TENANT_ID \
  --scope verification:write \
  --scope receipts:read \
  --rate-limit-per-minute 120
```

Issue a separate audit export key when needed:

```bash
python scripts/manage_neon_trust.py issue-api-key \
  --tenant-id TENANT_ID \
  --scope audit:export \
  --rate-limit-per-minute 20
```

The plaintext API key is returned only at issuance time. The database stores its SHA-256 hash.

## Provision an operator

```bash
python scripts/manage_neon_trust.py create-operator \
  --name "Risk Administrator"
```

Then issue a separate admin credential:

```bash
python scripts/manage_neon_trust.py issue-admin-key \
  --operator-id OPERATOR_ID \
  --scope audit:lifecycle
```

Tenant service credentials and operator credentials remain separate namespaces.

## Register the receipt signing key

Generate the Ed25519 keypair with the existing generator:

```bash
python scripts/generate_trust_signing_key.py
```

Keep the private key in your deployment secret store:

```bash
export GAIALAB_TRUST_SIGNING_KEY_B64="..."
```

Register only the public key in Neon:

```bash
python scripts/manage_neon_trust.py register-signing-key \
  --public-key-b64 "PUBLIC_KEY_B64" \
  --label "production-2026-01"
```

The active public-key lifecycle remains append-only (`registered`, `activated`, `retired`, `revoked`).

## Configure a tenant policy

```bash
python scripts/manage_neon_trust.py create-policy \
  --tenant-id TENANT_ID \
  --file config/trust_policies/example_fintech_strict.json \
  --note "Initial production controls"
```

Policy versions are immutable. Activation is an append-only event and the active policy ID/hash is bound into every verification receipt.

## Run the API

```bash
uvicorn src.trust_api:app --host 0.0.0.0 --port 8000
```

`GET /health` reports `storage_mode: neon` when the Neon backend is active.

## Runtime behavior

When `GAIALAB_DATABASE_URL` is configured, the same API routes use Neon for:

```text
X-API-Key authentication
        ↓
per-key rate limit row lock
        ↓
tenant policy lookup
        ↓
verification
        ↓
receipt persistence
        ↓
audit export
        ↓
audit lifecycle / legal hold
```

The Postgres rate limiter uses a row-level lock (`SELECT ... FOR UPDATE`) for each key/window so concurrent instances share one counter.

Receipt insertion checks an existing verification ID inside the same transaction before inserting, preserving write-once tenant ownership semantics.

## Local fallback

If `GAIALAB_DATABASE_URL` is absent, the existing SQLite environment variables continue to work:

- `GAIALAB_TENANT_DB`
- `GAIALAB_OPERATOR_DB`
- `GAIALAB_TENANT_POLICY_DB`
- `GAIALAB_RATE_LIMIT_DB`
- `GAIALAB_TRUST_KEY_REGISTRY_DB`
- `GAIALAB_TRUST_RECEIPT_DB`
- `GAIALAB_AUDIT_LIFECYCLE_DB`

This keeps the current test and local-development workflow intact while Neon becomes the production persistence layer.

## Current boundary

This slice provides a production database backend and transactional concurrency primitives. It does not yet include:

- Alembic-style versioned migrations
- automated backup/restore drills
- database-level Row Level Security policies
- read replicas or analytics replicas
- destructive retention execution
- application connection telemetry

Those should be added as later production-hardening slices rather than mixed into trust-policy logic.

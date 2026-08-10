# GaiaLab Naija Trust Rail MVP

The Trust Rail is a model-agnostic AI evidence and assurance layer for consequential Nigerian AI interactions. Automated findings remain advisory and never mutate governed human approval or release state.

## Current flow

```text
AI model -> candidate response -> deterministic claim extraction -> authoritative-state reconciliation
-> ALLOW / VERIFY / REWRITE / ESCALATE / BLOCK -> signed verification receipt -> tenant-scoped audit store
```

## Run the API

```bash
uvicorn src.trust_api:app --reload
```

Production-style verification now requires a tenant API key in `X-API-Key`.

## Tenant authentication

Configure a tenant registry:

```bash
export GAIALAB_TENANT_DB="data/trust_tenants.sqlite3"
python scripts/manage_trust_identity.py create-tenant --db "$GAIALAB_TENANT_DB" --name "Example Fintech"
python scripts/manage_trust_identity.py issue-api-key --db "$GAIALAB_TENANT_DB" --tenant-id TENANT_ID --label server
```

Only the API-key hash is stored. The plaintext API key is returned once at issuance and should be handled as a secret.

Verify a response:

```bash
curl -X POST http://127.0.0.1:8000/v1/verify \
  -H "Content-Type: application/json" \
  -H "X-API-Key: gaia_live_..." \
  -d '{
    "user_message": "What happened to my transfer?",
    "assistant_response": "Your transfer was successful.",
    "authoritative_state": {"transaction_status": "pending"},
    "model_name": "provider/model-name"
  }'
```

The tenant ID is bound into the verification receipt. Stored receipt lookup is tenant-scoped, so one tenant cannot retrieve another tenant's receipt by guessing or learning its ID.

## Automatic typed claim extraction

`src/claim_extraction.py` extracts a deliberately narrow and auditable set of consequential claims such as transaction status, refund/reversal status, account status, NGN fee/amount claims, refund ETA and simple delivery/completion ETA tokens. It records matched text, handles common negation and flags conflicting claims. Extraction is advisory only and never counts as evidence.

## Structured reconciliation

`src/claim_reconciliation.py` compares extracted or caller-supplied claims with `authoritative_state` and optional `evidence`. Outcomes are `SUPPORTED`, `UNSUPPORTED`, or `CONTRADICTED`. A contradicted high-impact claim can drive `BLOCK`; unsupported consequential claims trigger a stricter verification/rewrite path.

## Signed receipts and key rotation

Generate an Ed25519 keypair:

```bash
python scripts/generate_trust_signing_key.py
```

Keep the private key outside the repository:

```bash
export GAIALAB_TRUST_SIGNING_KEY_B64="..."
```

Configure the public-key registry:

```bash
export GAIALAB_TRUST_KEY_REGISTRY_DB="data/trust_signing_keys.sqlite3"
python scripts/manage_trust_identity.py register-signing-key \
  --db "$GAIALAB_TRUST_KEY_REGISTRY_DB" \
  --public-key-b64 PUBLIC_KEY_B64 \
  --label primary-2026
```

The registry stores public keys only. Lifecycle state is append-only through `registered`, `activated`, `retired`, and `revoked` events. A configured signing key must be registered and `active` before the API will issue signed receipts.

For rotation, generate/register the new key, switch the deployment secret, then retire the old key:

```bash
python scripts/manage_trust_identity.py transition-signing-key \
  --db "$GAIALAB_TRUST_KEY_REGISTRY_DB" \
  --key-id OLD_KEY_ID --event retired --reason rotation
```

Use `revoked` when a key should no longer be trusted operationally, such as after suspected compromise. Historical signatures remain cryptographically checkable, while registry status communicates current trust state.

Public discovery endpoints:

```text
GET /v1/signing-keys
GET /v1/signing-keys/{key_id}
POST /v1/receipts/verify
```

## Tenant-scoped append-only receipts

```bash
export GAIALAB_TRUST_RECEIPT_DB="data/trust_receipts.sqlite3"
```

For an existing `verification_id`, identical content under the same tenant is idempotent; different content or attempted tenant rebinding raises a conflict instead of overwriting history.

Authenticated endpoints:

```text
POST /v1/verify
GET /v1/receipts/{verification_id}
GET /v1/receipts/{verification_id}/verify
```

## Security boundaries

- private signing keys never belong in Git or the public-key registry
- only hashed tenant API keys are stored
- stored receipts are isolated by tenant ID
- public receipt verification proves signature integrity, not truthfulness of upstream business data
- automated dispositions do not constitute governed human approval
- SQLite remains an MVP persistence layer; enterprise deployment should use managed secrets, rate limiting, authorization roles, transactional audit storage, backups and retention controls

## Synthetic benchmark

The initial Nigerian fintech benchmark remains deliberately synthetic engineering coverage. It is not culturally validated, training-eligible data or evidence of production model quality.

## Next build sequence

1. Add organization-specific policy packs and per-tenant configuration.
2. Add rate limits, scoped API-key roles and an operator/admin authorization boundary.
3. Move the append-only audit contract to a managed transactional backend with export/retention controls.
4. Expand Nigerian English/Pidgin extraction using governed reviewer benchmarks.
5. Add provider adapters for OpenAI, Anthropic, Gemini, Qwen, N-ATLAS and private models.
6. Add the Trust Dashboard for tenant/model risk analytics, receipt search and audit exports.
7. Evaluate optional model-assisted extraction behind the deterministic boundary before enabling it.

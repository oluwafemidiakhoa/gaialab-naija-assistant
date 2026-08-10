# Operator Action Audit Log

GaiaLab Naija Trust Rail records privileged administration in a tamper-evident SHA-256 action chain.

## What is recorded

The ledger covers operator lifecycle and destructive-retention mutations automatically through audited storage wrappers. The Neon provisioning CLI also records successful mutations to:

- tenants;
- tenant API keys;
- operators;
- admin API keys;
- tenant policies;
- signing keys.

Provisioning mutations require an explicit `--actor-id` or `GAIALAB_PROVISIONING_ACTOR_ID` so changes are attributable to a human/operator identity.

## Chain structure

Each action contains:

- a random `action_id`;
- operator/actor ID;
- optional key ID;
- action type;
- target type;
- SHA-256 of the target identifier, not the raw target ID;
- sanitized metadata;
- previous action hash;
- creation timestamp;
- SHA-256 action hash.

The global chain starts from a fixed 64-zero genesis hash. Neon serializes appends by locking `operator_action_log_heads` with `FOR UPDATE`; SQLite uses `BEGIN IMMEDIATE`.

## Requested and completed actions

Privileged API storage mutations use two records:

```text
<action>.requested
<action>.completed
```

The requested record is appended before the underlying mutation. If that mutation fails, the requested record remains and there is no completed record. This makes attempted privileged changes visible.

Provisioning CLI changes currently record the successful `completed` action after the provisioning mutation succeeds.

## Privacy and secret minimization

Raw target IDs are not stored in the ledger. Target IDs are deterministically SHA-256 hashed so actions against the same target can be correlated.

Metadata keys containing secret-like terms such as `password`, `secret`, `token`, `api_key`, `private_key`, or `database_url` are rejected recursively.

Issued tenant/admin API key values and database credentials are never copied into action metadata.

Deterministic target hashes provide correlation rather than anonymity against a party that can guess a known identifier. A keyed target digest can replace this later if stronger identifier confidentiality is required.

## Verification

`verify_chain()` recomputes every action hash from the genesis hash and verifies:

1. each `previous_action_hash` points to the prior computed hash;
2. each stored action hash matches canonical action content;
3. the final computed hash equals the separately stored chain head.

The stored-head comparison detects a deleted or truncated tail even when the remaining rows still form a valid prefix.

The current verifier refuses to certify chains larger than 10,000 actions rather than silently validating only a prefix. Production scale should replace this bound with checkpointed or paginated chain verification.

Provisioning CLI inspection commands:

```text
python scripts/manage_neon_trust.py list-operator-actions --limit 100
python scripts/manage_neon_trust.py verify-operator-actions
```

## Database privileges

Tenant runtime has no privileges on operator action tables.

Operator runtime receives only:

- `SELECT`, `UPDATE` on `operator_action_log_heads`;
- `SELECT`, `INSERT` on `operator_actions`;
- sequence usage for action event IDs.

It receives no `DELETE` or direct `UPDATE` privilege on historical `operator_actions` rows.

The migration/owner identity can modify schema and therefore remains a higher-trust administrative credential.

## Integrity boundary

The hash chain is tamper-evident, not an external transparency log. A database owner with sufficient privileges could rewrite both rows and the stored head. For stronger non-repudiation, future hardening should periodically sign/export chain checkpoints to an independent system or transparency service.

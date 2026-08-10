# Externally Signed Operator-Action Checkpoints

GaiaLab Trust Rail's operator action log is already an append-only SHA-256 chain with a separately stored database head. That detects many forms of accidental or unauthorized mutation, but a sufficiently privileged database owner could rewrite both the rows and the stored head.

Operator checkpoints add an independently portable Ed25519-signed statement of the chain state at a specific point in time.

## What a checkpoint binds

Each checkpoint signs:

- checkpoint format version
- operator stream ID (`global` in v0.1)
- exact operator action count
- exact SHA-256 chain head
- UTC creation timestamp
- deterministic checkpoint ID derived from those fields

The signature package includes the signing public key and key ID so the bytes can be verified offline.

## What this improves

A checkpoint that is copied to independently controlled storage can later detect:

- deletion/truncation of actions below the checkpoint count
- rewriting a chain to a different head at the same count
- rewriting an older prefix even when new actions were appended afterward
- checkpoint-field or signature tampering
- a checkpoint signed by a key other than the independently trusted key ID

This changes the trust boundary from "trust the database owner not to rewrite both the chain and its head" to "also compromise or replace the independently retained checkpoint and trusted signer identity."

## What this does not do

A signed checkpoint does **not** prevent database tampering. It detects divergence from independently retained evidence.

The public key embedded in a checkpoint proves cryptographic integrity only. It does not, by itself, prove that the signer is an authorized GaiaLab checkpoint signer. Verifiers should pin the expected key ID through a separate trusted channel.

A checkpoint is not a governed dataset approval, model approval, publication approval, deletion approval, or customer-response delivery decision. It is operator-ledger evidence only.

## Key handling

Use a dedicated Ed25519 checkpoint signing key rather than reusing a provider credential or database credential. Production deployments should preferably keep the private key in an external secret manager or signing service.

The local CLI reads the private key only from:

```text
GAIALAB_OPERATOR_CHECKPOINT_SIGNING_KEY_B64
```

Do not commit this value to Git, database rows, logs, screenshots, issue comments, or checkpoint files.

## Create a checkpoint

Configure the operator action log in the same way as the rest of the Trust Rail runtime, then set the checkpoint signing key in the process environment.

```bash
python scripts/operator_checkpoint.py create --output /secure/external/gaialab-operator-checkpoint.json
```

The file contains the signed checkpoint package. Standard output reports only non-secret identifiers and hashes.

The v0.1 implementation supports the single existing `global` operator stream. It refuses arbitrary stream labels so the signed label cannot misrepresent which chain was certified.

## Verify offline

Offline verification requires only the checkpoint JSON file. Pin the signer key ID obtained through a separate trusted channel:

```bash
python scripts/operator_checkpoint.py verify \
  --file /secure/external/gaialab-operator-checkpoint.json \
  --expected-key-id EXPECTED_CHECKPOINT_KEY_ID
```

This verifies checkpoint structure, deterministic content binding, Ed25519 signature validity, and signer identity against the expected key ID.

## Verify against the current operator chain

With operator database access configured:

```bash
python scripts/operator_checkpoint.py verify-current \
  --file /secure/external/gaialab-operator-checkpoint.json \
  --expected-key-id EXPECTED_CHECKPOINT_KEY_ID
```

Possible successful states include:

- `checkpoint_matches_current_chain` — current count and head exactly match the checkpoint
- `checkpoint_is_valid_ancestor` — newer actions exist, but the historical action at the checkpoint position still has the signed head

Important divergence states include:

- `operator_chain_truncated_since_checkpoint`
- `operator_chain_rewritten_since_checkpoint`
- `operator_chain_history_rewritten_since_checkpoint`
- `current_operator_chain_invalid`
- `unexpected_signing_key`

## External retention recommendations

For stronger evidence, copy checkpoints to storage that is operationally independent from the Trust Rail database. Examples include an immutable object store, evidence vault, customer-controlled archive, or separate transparency service.

Retain the trusted signer key ID and key-lifecycle records independently as well. If both the checkpoint file and trust record are stored only in the same database controlled by the same administrator, the security benefit is significantly reduced.

A future hardening layer can periodically publish checkpoint hashes or signatures to a separately operated transparency service. The v0.1 implementation deliberately stops at portable signed evidence and does not claim public-transparency-log guarantees.

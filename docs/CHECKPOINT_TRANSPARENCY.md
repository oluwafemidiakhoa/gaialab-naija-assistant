# Independent checkpoint transparency publication

GaiaLab Trust Rail can publish signed operator checkpoints into an independently retained transparency ledger without exposing operator action contents, governed datasets, private keys, provider credentials, tenant secrets, or approval state.

## Security model

There are two integrity layers:

1. the existing Ed25519 checkpoint signature protects the operator-chain statement (`action_count`, `action_head_sha256`, stream, timestamp, checkpoint ID), and
2. the transparency JSONL ledger hash-chains publication entries so rewrite, reorder, insertion, and deletion in the middle are detected.

Tail deletion requires one additional operational control: retain the latest transparency `head_sha256` through a channel independent from the ledger itself. Verification with `--expected-head-sha256` then detects rollback to an older but internally valid prefix.

The ledger is useful only when its storage and trusted checkpoint signer identity are operationally independent from the Trust Rail database owner. A copy stored beside the same mutable database under the same administrator does not materially strengthen the trust boundary.

## Published fields

`src/checkpoint_transparency.py` accepts only the exact public checkpoint and signature shapes. Unexpected fields fail closed.

A transparency record contains:

- deterministic publication ID
- checkpoint-package SHA-256
- checkpoint ID and format version
- global stream ID
- operator action count
- operator action-chain head SHA-256
- checkpoint creation timestamp
- Ed25519 signature version, algorithm, public key, key ID, and signature

It does **not** contain operator IDs, action types, action targets, action metadata, tenant records, customer content, receipts, database credentials, signing private keys, or governed review decisions.

## Trusted signer identity

The embedded public key proves cryptographic validity, not authorization. Production publication and verification should provide one or more independently trusted checkpoint key IDs.

A cryptographically valid checkpoint signed by an unknown key is rejected when `trusted_key_ids` / `--trusted-key-id` is supplied.

## Create a transparency record

Start with an existing signed checkpoint from `scripts/operator_checkpoint.py`.

```bash
python scripts/checkpoint_transparency.py record \
  --checkpoint /secure/checkpoints/operator-checkpoint.json \
  --output /external/transparency/checkpoint-record.json \
  --trusted-key-id EXPECTED_CHECKPOINT_KEY_ID
```

The command refuses to overwrite an existing output path.

## Append to the independent ledger

```bash
python scripts/checkpoint_transparency.py append \
  --record /external/transparency/checkpoint-record.json \
  --ledger /external/transparency/operator-checkpoints.jsonl \
  --trusted-key-id EXPECTED_CHECKPOINT_KEY_ID
```

Existing entries are never rewritten by the append operation. The command returns the new `head_sha256`; retain that value independently, for example in a separate evidence vault, customer-controlled archive, immutable object-store metadata, or another transparency operator.

Duplicate checkpoint publication is rejected.

## Verify one record offline

```bash
python scripts/checkpoint_transparency.py verify-record \
  --file /external/transparency/checkpoint-record.json \
  --trusted-key-id EXPECTED_CHECKPOINT_KEY_ID
```

This recomputes the checkpoint-package digest and deterministic publication ID, verifies the checkpoint Ed25519 signature, and optionally pins signer identity.

## Verify the ledger

```bash
python scripts/checkpoint_transparency.py verify-log \
  --ledger /external/transparency/operator-checkpoints.jsonl \
  --trusted-key-id EXPECTED_CHECKPOINT_KEY_ID \
  --expected-head-sha256 INDEPENDENTLY_RETAINED_HEAD
```

Verification checks:

- sequential numbering
- previous-entry hash linkage
- canonical entry hashes
- checkpoint-package hashes
- deterministic publication IDs
- checkpoint signatures
- trusted checkpoint signer IDs when configured
- duplicate checkpoint/publication IDs
- optional externally pinned ledger head

## What this does not claim

This implementation is a portable, independently retainable transparency ledger. It is **not** a globally witnessed Certificate-Transparency-style service and does not claim consensus, public gossip, multi-party witnessing, blockchain anchoring, or guaranteed third-party availability.

It does not approve datasets, models, deletion plans, customer responses, training eligibility, Nigerian cultural validation, or publication of governed content. Only signed operator-chain evidence is eligible for this transparency path.

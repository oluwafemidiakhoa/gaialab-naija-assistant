# Audit Evidence Integrity

GaiaLab Naija Audit Evidence Packages are portable tenant-scoped collections of Trust Rail verification receipts. Package verification must derive integrity from the exported evidence itself rather than trusting convenience fields copied from storage.

## Verification contract

`verify_audit_package()` verifies the current `gaialab-naija-audit-export/0.2.0` package format without changing its wire shape.

For every non-empty package, the verifier:

1. recomputes the manifest `package_id` from canonical JSON of the manifest core;
2. binds manifest `entry_ids`, `entry_hashes`, and `entry_count` to the actual exported entries;
3. rejects duplicate entry IDs;
4. verifies the optional manifest Ed25519 signature when present;
5. requires every receipt entry to contain a receipt signature;
6. binds each entry `verification_id` to the embedded verification receipt;
7. binds each embedded receipt `tenant_id` to the manifest tenant;
8. reconstructs the exact persisted envelope `{verification_receipt, signature}` and recomputes its canonical SHA-256;
9. compares that recomputed SHA-256 with the exported `payload_sha256`;
10. directly verifies the embedded receipt Ed25519 signature;
11. recomputes disposition, model, finding-code, and integrity-failure summary values from verified receipts.

The exported `payload_integrity_valid` and `signature_valid` fields remain in the package for backward-compatible observability, but the verifier never treats them as authoritative.

## Fail-closed behavior

A package is invalid when evidence is malformed or missing, including:

- malformed entries or hashes;
- missing receipt signatures;
- verification-ID mismatch;
- cross-tenant receipt transplantation;
- canonical envelope hash mismatch;
- invalid receipt signatures;
- invalid manifest signatures;
- entry-count or manifest-entry mismatch;
- recomputed summary mismatch.

An empty package remains valid when its manifest is internally consistent because it contains no receipt entry that requires a signature.

## Threat model

The hardened verifier catches an attacker who changes a receipt and merely flips exported booleans back to `true`. It also catches an attacker who changes a receipt and rewrites the exported payload hash and unsigned manifest, because the original receipt signature no longer verifies.

A manifest signature authenticates the package manifest when present. Receipt signatures authenticate individual verification receipts. Cryptographic validity does not by itself establish that a signing key was authorized at a particular historical time; key-registry or externally pinned trust decisions remain separate operational policy.

## Canonicalization

Envelope hashing uses deterministic JSON serialization with UTF-8 encoding, sorted keys, compact separators, `ensure_ascii=False`, and `default=str`. This matches receipt persistence semantics so audit verification does not invent a second hash format.

## CI coverage

The `Audit Evidence Integrity` GitHub Actions workflow runs focused tamper regressions for:

- canonical envelope hash recomputation;
- receipt signature recomputation;
- forged stored integrity flags;
- attacker-updated hashes and manifests;
- missing signatures;
- tenant transplantation;
- manifest-signature tampering;
- backend-provided integrity-boolean distrust.

The workflow also compiles the audit evidence, receipt storage, and signing modules.

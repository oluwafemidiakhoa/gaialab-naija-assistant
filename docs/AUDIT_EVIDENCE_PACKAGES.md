# GaiaLab Naija Audit Evidence Packages

Audit Evidence Packages turn tenant-owned verification receipts into portable, privacy-preserving audit artifacts.

They are designed for internal risk review, compliance investigations, model-performance review, incident response, and evidence exchange without exporting raw prompts, authoritative business state, or customer evidence.

## Authorization

Creating an export requires an API key with:

```text
audit:export
```

The export is always scoped to the authenticated tenant. Stored receipts belonging to other tenants are not selectable.

Public package verification does not require tenant credentials because verification operates only on the package supplied by the caller.

## Create an export

```text
POST /v1/audit/exports
X-API-Key: <tenant audit key>
```

Example body:

```json
{
  "created_from": "2026-07-01 00:00:00",
  "created_to": "2026-07-31 23:59:59",
  "dispositions": ["BLOCK", "ESCALATE"],
  "limit": 10000
}
```

The package contains:

- a manifest with tenant ID, filters, package ID, receipt IDs, receipt payload hashes, counts, and generation timestamp
- summary counts by disposition, model, and finding code
- stored verification receipts and their signatures
- storage-level SHA-256 integrity results
- receipt-signature validation results
- an optional Ed25519 signature over the deterministic manifest core when a Trust Rail signing key is configured

The export does **not** include raw user prompts, raw evidence values, or raw authoritative business state.

## Verify an export

```text
POST /v1/audit/verify
```

The verifier checks:

1. package ID against the canonical manifest core
2. entry ordering and receipt IDs against the manifest
3. stored payload hashes
4. embedded verification-receipt signatures when present
5. optional package-manifest signature when present

Any entry mismatch, receipt-signature failure, or manifest-signature failure causes package verification to fail.

## Example result

```json
{
  "valid": true,
  "reason": "audit_package_valid",
  "package_id": "...",
  "signed": true,
  "entry_count": 42
}
```

## Trust boundary

An Audit Evidence Package proves the integrity and provenance of GaiaLab's stored verification records. It does not prove that upstream banking, transaction, account, or customer data supplied to GaiaLab was truthful.

The package is an evidence container, not a regulator certification and not a human governance approval.

## Current implementation

The MVP uses the tenant-scoped append-only SQLite receipt store. Production deployment should move the same semantics to a transactional managed audit backend with durable retention policies, access logs, legal holds, export lifecycle records, and independent backup/restore verification.

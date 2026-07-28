# Public dataset release verification

GaiaLab's public verification layer checks immutable files under
`data/releases/<version>/`. It is read-only: it never changes a release, registry
snapshot, review event, or original dataset.

Verification certificates intentionally exclude:

- reviewer names or identifiers;
- quality scores and review notes;
- prompts, responses, and system messages;
- raw source strings;
- ownership, consent, and provenance evidence; and
- private filesystem paths.

Only a public source classification is returned: `synthetic`,
`recovered_legacy`, `documented`, or `unknown`.

## Command-line verification

Verify a record by ID:

```bash
python scripts/dataset_platform.py verify \
  --record-id v06-banking-001
```

Narrow the lookup to a release:

```bash
python scripts/dataset_platform.py verify \
  --version v0.6 \
  --record-id v06-banking-001
```

Verify by record hash:

```bash
python scripts/dataset_platform.py verify \
  --record-sha256 <64-character-sha256>
```

Verify the release envelope by its manifest hash:

```bash
python scripts/dataset_platform.py verify \
  --manifest-sha256 <64-character-sha256>
```

Selectors can be combined. When both record ID and record hash are supplied, the
same current record must match both. The command exits with status zero only for
`verified` and `superseded` certificates. Unknown, altered, and malformed
requests return a non-zero status.

## Integrity statuses

- `verified`: the release manifest is readable, its version and record count
  match, every published file matches its manifest hash, and the record's stored
  hash matches recomputed canonical content.
- `altered`: the release or record exists, but at least one integrity check
  fails.
- `superseded`: the queried historical record hash is retained in a current
  record's `supersedes_sha256` field. The certificate identifies the current
  replacement hash without exposing record content.
- `unknown`: no matching release, record, or superseded hash was found.

Version-only and manifest-only requests verify the release envelope and do not
claim that a particular record exists.

## Public Streamlit application

Launch the standalone read-only verifier:

```bash
streamlit run app/dataset_verify.py
```

The same verifier is available as the **Release Verification** page when the
dataset review application is launched:

```bash
streamlit run app/dataset_review.py
```

Set `GAIALAB_RELEASES_DIR` to use a different public release root. The application
only reads release files and offers the sanitized certificate as a JSON download.

## Certificate fields

A certificate includes:

- queried identifiers;
- whether the release and record exist;
- release version and manifest SHA-256;
- record ID and record SHA-256;
- category and public source classification;
- license and review status;
- revision, creation timestamp, and approval timestamp;
- integrity status and individual integrity checks; and
- the replacement hash when a queried hash is superseded.

Draft or rejected records have a null approval timestamp. Approval time is shown
only when the public record's review status is `approved`.

## Reproducibility

Run:

```bash
python -m pytest
python scripts/dataset_platform.py verify --version v0.6
```

For independent manifest verification, compute the hash of
`data/releases/<version>/dataset_manifest.json` with a standard SHA-256 utility
and submit that value through the CLI or application.

# Legacy provenance recovery

This workflow audits GaiaLab Naija v0.4 and v0.5 without changing their original
JSONL files or treating repository lineage as proof of ownership, consent, or a
license.

The current audit found build lineage for every record, but no per-record dataset
source or license. All current rows are therefore `provenance_recoverable`, not
`provenance_complete`. No legacy record is eligible for import until a human
reviewer supplies repository-verifiable evidence for every required value.

## Classification

- `provenance_complete`: the original record contains a non-empty source and
  license. This classification does not itself constitute human approval.
- `provenance_recoverable`: repository evidence identifies an upstream record or
  build lineage, but one or more provenance fields remain unresolved.
- `provenance_unknown`: no useful upstream lineage or complete provenance was
  found.
- `rejected`: the legacy record is malformed or a human reviewer explicitly
  rejects it.

Lineage can show that one file was used to create another. It cannot prove who
wrote the content, who owns it, whether consent was obtained, or which license
applies.

## Evidence discovered

The v0.4 build is traceable to the four `data/raw/*.jsonl` files, the build script,
manifest, and Git commit
`c564287aeabbcedaef1efdf88a8b92b46d683560`. The v0.5 manifest identifies its
v0.4 training base and two new-example inputs; commit
`51c4aa9b5d346e4eba1c5adb5b397c241bd165a9` preserves those files.

These are exact lineage references only. Neither commit message, manifest, build
script, nor adjacent record establishes a per-record license, ownership basis, or
consent status. The repository's MIT software license must not be assumed to
license dataset content.

## Run the audit

From the repository root with Python 3.11:

```bash
python scripts/audit_legacy_provenance.py \
  --output data/legacy_review/provenance_audit.json

python scripts/prepare_legacy_review.py \
  --output-dir data/legacy_review
```

Audit reports and review sheets are write-once. The commands refuse to overwrite
an existing path so reviewer work is not lost.

The review sheets contain the requested review columns plus:

- `classification`;
- `original_sha256`;
- general `evidence_references`; and
- separate source, license, ownership, and consent evidence references.

Automated proposed values are always blank unless the original record already
contains them. For this audit all proposed provenance values remain blank.

## Human review

For an importable row, a human reviewer must:

1. inspect the original prompt and response;
2. find repository evidence that explicitly states the source, license,
   ownership basis, and consent status;
3. enter each value exactly as supported by that evidence;
4. enter an exact `path:line` or Git evidence reference in each corresponding
   evidence column;
5. enter a stable reviewer name or ID and review notes; and
6. set `review_status` to `approved`.

The importer reads only literal evidence. Each proposed value must appear in the
referenced repository line or Git commit text. Merely citing a lineage file is
insufficient. If the evidence lives outside the repository, add a lawful,
non-sensitive review artefact to the repository first; do not add private data,
signatures, identity documents, or confidential agreements.

Use `rejected` when a human determines the record must not be migrated. Leave the
status blank or use a non-approved status while provenance remains unresolved.

## Approval-gated import

After human review:

```bash
python scripts/import_reviewed_legacy.py \
  data/legacy_review/v0.4_provenance_review.csv \
  data/legacy_review/v0.5_provenance_review.csv
```

The importer:

- reloads content from the untouched original JSONL files;
- verifies each review row's `original_sha256`;
- requires explicit human approval and reviewer identity;
- verifies separate evidence for source, license, ownership, and consent;
- rejects unsupported proposed values;
- skips exact content already migrated from another version;
- retains `legacy_original_sha256` on every accepted record;
- creates a new write-once `<version>-legacy-recovered` registry snapshot; and
- writes a timestamped migration report with accepted, rejected, unresolved, and
  duplicate counts.

It never changes `data/v0.4/` or `data/v0.5/`. If there are no accepted rows, no
registry snapshot is created.

## Reproducibility checks

```bash
python -m pytest
python scripts/audit_legacy_provenance.py
```

Before committing a human-reviewed migration, confirm:

- original v0.4 and v0.5 hashes are unchanged;
- every accepted row has four value-specific evidence references;
- accepted source and license values are compatible with redistribution;
- duplicates were reviewed rather than silently imported; and
- the migration report and immutable recovered snapshot are included.

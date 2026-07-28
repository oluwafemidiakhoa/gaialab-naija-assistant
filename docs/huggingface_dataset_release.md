# Offline Hugging Face dataset release

The exporter creates a local package and never uploads it. By default only
training-eligible records are split into train, validation, and benchmark files.
`--include-drafts` places unapproved rows in a separate `drafts.jsonl` with a
prominent warning; drafts are never silently mixed into training.

```bash
python scripts/export_huggingface_dataset.py --version v0.6 \
  --output-dir exports/huggingface/gaialab-naija-v0.6
```

Before writing, the exporter verifies release and record hashes, provenance, and
record-level licences. It strips internal reviewer data, scans public content for
private fields and secret-like values, and refuses existing output paths. The
package includes a card, validation report, public certificate, scorecard, and
SHA-256 checksum list. A successful export establishes integrity, not cultural
validation or suitability for high-risk use.

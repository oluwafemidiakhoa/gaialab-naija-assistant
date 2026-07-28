# Training eligibility

`build_training_release.py` refuses draft, rejected, superseded, unlicensed,
unprovenanced, duplicate, hash-invalid, or incompletely reviewed records. Critical
quality findings also exclude a record. Decisions are hashed and explain every
exclusion.

Use `--dry-run` to inspect counts without writing. A real run creates a write-once
release candidate and deterministic category/risk splits. The held-out benchmark
is checked against training and validation IDs and normalized prompts.

```bash
python scripts/build_training_release.py --source-version v0.6 \
  --target-version v0.7-rc1 --dry-run
```

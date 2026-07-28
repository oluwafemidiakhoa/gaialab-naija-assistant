# Model verification

The public model certificate links a model release to its training run, dataset
manifest, script, adapter, and evaluation report hashes. It contains no local
paths, usernames, environment variables, secrets, or reviewer data.

```bash
python scripts/model_platform.py verify-release --model-version v0.6
```

An unregistered model or any missing/mismatched artifact produces
`integrity_status: unverified`. Verification proves integrity of registered
bytes; it does not prove model quality or safety.

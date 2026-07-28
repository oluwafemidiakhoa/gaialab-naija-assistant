# Model and training-run registry

Training runs, individual artifacts, and releases are stored as write-once JSON
records with canonical SHA-256 hashes. Registration records the exact dataset
manifest, splits, training script, base-model revision, environment, seed, LoRA
configuration, timestamps, and metrics. Registration does not start training.

```bash
python scripts/model_platform.py register-run --config training/run_config_v06.json
python scripts/model_platform.py register-artifacts --run-id RUN_ID --output-dir outputs/adapter
python scripts/model_platform.py create-release --run-id RUN_ID --model-version v0.6
```

Reusing an ID or release version is rejected. Verification detects missing or
altered scripts and artifacts.

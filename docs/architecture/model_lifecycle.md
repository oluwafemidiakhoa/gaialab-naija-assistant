# Model lifecycle

Training is always an explicit command. Before training, an eligible release
candidate fixes train, validation, and held-out benchmark hashes. A registered
run records the dataset manifest, script hash, base-model revision, random seed,
LoRA configuration, environment, timestamps, and metrics.

Generated artifacts remain under ignored output directories. Each registered
artifact has a path-independent registry identity, size, and file hash. A model
release progresses through candidate, evaluated, approved, published, or
deprecated status; the current implementation never promotes status
automatically. Public verification links a model back to its dataset and detects
missing or altered artifacts.

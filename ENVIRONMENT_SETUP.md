# GaiaLab Naija reproducible environment

## Windows CPU

From the repository root:

```cmd
setup_windows.bat
run_gaialab_v04_automatic.bat
```

The setup creates `.venv`, installs a matched CPU-only PyTorch build, installs pinned Hugging Face dependencies, and validates imports.

The benchmark runner then:

1. Uses the isolated `.venv`.
2. Downloads `mgbam/gaialab-naija-adapter-v0.3` when missing.
3. Validates the environment.
4. Backs up the previous CSV.
5. Runs the v0.4 benchmark.

## Why torchvision is not installed

GaiaLab's benchmark is text-only. It does not need torchvision. Omitting it avoids mismatched `torchvision::nms` binaries and reduces the environment size.

## Git

Commit the setup files, but do not commit the virtual environment or downloaded model files. Add these entries to `.gitignore`:

```gitignore
.venv/
models/v0.3/best_adapter/
evaluation/v0.4/*_backup.csv
```

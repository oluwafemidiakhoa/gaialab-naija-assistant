#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "=========================================="
echo "GaiaLab Naija - Linux CPU Setup"
echo "=========================================="

python3 -m venv .venv
PYTHON=".venv/bin/python"

"$PYTHON" -m pip install --upgrade pip setuptools wheel
"$PYTHON" -m pip uninstall -y torchvision torchaudio >/dev/null 2>&1 || true
"$PYTHON" -m pip install --upgrade --force-reinstall torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
"$PYTHON" -m pip install --upgrade --force-reinstall -r requirements-cpu.txt
"$PYTHON" scripts/verify_environment.py

echo "Setup completed successfully."

@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: .venv\Scripts\python.exe was not found.
    echo Copy this pack into the root of gaialab-naija-assistant first.
    pause
    exit /b 1
)

.venv\Scripts\python.exe scripts\build_v04_dataset.py --input-dir data\raw --output-dir data\v0.4 --validation-ratio 0.10 --seed 42

if errorlevel 1 (
    echo.
    echo Dataset preparation failed.
    pause
    exit /b 1
)

echo.
echo Dataset files created under data\v0.4
pause

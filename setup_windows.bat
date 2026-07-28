@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo.
echo ==========================================
echo GaiaLab Naija - Windows CPU Setup
echo ==========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python was not found in PATH.
    echo Install Python 3.10, 3.11, or 3.12 and try again.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating isolated virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :failed
)

set "PYTHON=.venv\Scripts\python.exe"

echo Upgrading pip...
"%PYTHON%" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto :failed

echo Removing incompatible vision packages if present...
"%PYTHON%" -m pip uninstall -y torchvision torchaudio >nul 2>nul

echo Installing the official CPU build of PyTorch...
"%PYTHON%" -m pip install --upgrade --force-reinstall torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 goto :failed

echo Installing pinned GaiaLab dependencies...
"%PYTHON%" -m pip install --upgrade --force-reinstall -r requirements-cpu.txt
if errorlevel 1 goto :failed

echo Verifying the environment...
"%PYTHON%" scripts\verify_environment.py
if errorlevel 1 goto :failed

echo.
echo ==========================================
echo Setup completed successfully.
echo Run: run_gaialab_v04_automatic.bat
echo ==========================================
echo.
pause
exit /b 0

:failed
echo.
echo ERROR: GaiaLab environment setup failed.
echo Review the messages above, then try again.
pause
exit /b 1

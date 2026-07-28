@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo.
echo ==========================================
echo GaiaLab Naija v0.4 Automatic Benchmark
echo ==========================================
echo.

set "PYTHON=.venv\Scripts\python.exe"
set "ADAPTER=models\v0.3\best_adapter"
set "ADAPTER_REPO=mgbam/gaialab-naija-adapter-v0.3"

if not exist "%PYTHON%" (
    echo ERROR: The GaiaLab virtual environment does not exist.
    echo Run setup_windows.bat first.
    pause
    exit /b 1
)

if not exist "scripts\run_v04_benchmark.py" (
    echo ERROR: scripts\run_v04_benchmark.py was not found.
    pause
    exit /b 1
)

if not exist "evaluation\v0.4\benchmark_v0.4.jsonl" (
    echo ERROR: evaluation\v0.4\benchmark_v0.4.jsonl was not found.
    pause
    exit /b 1
)

if not exist "%ADAPTER%\adapter_config.json" (
    echo The v0.3 adapter is not available locally.
    echo Downloading %ADAPTER_REPO%...
    "%PYTHON%" -m huggingface_hub.commands.huggingface_cli download "%ADAPTER_REPO%" --local-dir "%ADAPTER%" >nul 2>nul

    if not exist "%ADAPTER%\adapter_config.json" (
        echo Retrying with the hf executable...
        if exist ".venv\Scripts\hf.exe" (
            ".venv\Scripts\hf.exe" download "%ADAPTER_REPO%" --local-dir "%ADAPTER%"
        ) else (
            echo ERROR: The Hugging Face CLI is unavailable.
            echo Run setup_windows.bat again.
            pause
            exit /b 1
        )
    )
)

if not exist "%ADAPTER%\adapter_config.json" (
    echo ERROR: Adapter download did not produce adapter_config.json.
    pause
    exit /b 1
)

echo Checking the environment...
"%PYTHON%" scripts\verify_environment.py
if errorlevel 1 (
    echo ERROR: Environment validation failed.
    echo Run setup_windows.bat again.
    pause
    exit /b 1
)

if exist "evaluation\v0.4\v0.3_baseline_review.csv" (
    copy /Y "evaluation\v0.4\v0.3_baseline_review.csv" "evaluation\v0.4\v0.3_baseline_review_backup.csv" >nul
)

echo.
echo Running all benchmark prompts...
echo.

"%PYTHON%" scripts\run_v04_benchmark.py ^
  --adapter "%ADAPTER%" ^
  --base-model "Qwen/Qwen2.5-0.5B-Instruct" ^
  --model-version "v0.3" ^
  --output "evaluation\v0.4\v0.3_baseline_review.csv"

if errorlevel 1 (
    echo.
    echo ERROR: Benchmark execution failed.
    pause
    exit /b 1
)

echo.
echo Benchmark completed successfully.
echo Output: evaluation\v0.4\v0.3_baseline_review.csv
echo.

start "" "evaluation\v0.4\v0.3_baseline_review.csv"
pause
endlocal

@echo off
rem Double-click to start SAR Log. First run sets up Python packages.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo First run: setting up...
    py -3 -m venv .venv || python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -e .
)
.venv\Scripts\python.exe -m sar_log serve
pause

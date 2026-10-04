@echo off
rem Double-click to start SAR Log. The first run sets up Python packages.
rem Updates may replace this file while it runs, so the last line must stay a
rem single line: cmd reads the whole line before running it, and "exit /b"
rem stops cmd from reading anything after it in the (possibly new) file.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo First run: setting up...
    py -3 -m venv .venv || python -m venv .venv
    .venv\Scripts\python.exe -m pip install --upgrade pip
    .venv\Scripts\python.exe -m pip install -e .
)
.venv\Scripts\python.exe -m sar_log launch & exit /b

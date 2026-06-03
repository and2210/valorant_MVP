@echo off
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe tools\rebuild_sqlite.py
) else (
    python tools\rebuild_sqlite.py
)
pause

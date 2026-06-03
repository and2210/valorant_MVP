@echo off
setlocal
cd /d "%~dp0"

if exist .venv\Scripts\python.exe (
    .venv\Scripts\python.exe app.py --terminal
) else (
    python app.py --terminal
)

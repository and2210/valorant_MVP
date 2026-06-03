@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\pyvenv.cfg" if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" app.py --gui
    exit /b
)

if exist ".venv\pyvenv.cfg" if exist ".venv\Scripts\python.exe" (
    start "" ".venv\Scripts\python.exe" app.py --gui
    exit /b
)

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe app.py --gui
    exit /b
)

start "" python.exe app.py --gui

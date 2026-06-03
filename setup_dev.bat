@echo off
setlocal
cd /d "%~dp0"

echo ================================================
echo RADIANE DESKTOP - SETUP DEV
echo ================================================

if not exist .venv (
    py -3.10 -m venv .venv
    if errorlevel 1 (
        echo Falha ao criar .venv com py -3.10. Tentando python...
        python -m venv .venv
    )
)

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python tools\rebuild_sqlite.py

echo ================================================
echo Setup concluido.
echo Use run_dev_gui.bat para abrir o app.
echo ================================================
pause

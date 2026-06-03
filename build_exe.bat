@echo off
setlocal
cd /d "%~dp0"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

pyinstaller --clean --noconfirm MVP-KCred.spec

if errorlevel 1 (
    echo.
    echo Build falhou. Rode build_exe_debug.bat para gerar a versao com console.
    pause
    exit /b 1
)

echo.
echo Build concluido.
echo Executavel: dist\MVP-KCred.exe
echo.
pause

@echo off
setlocal
cd /d "%~dp0"

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

pyinstaller --clean --noconfirm MVP-KCred-Debug.spec

if errorlevel 1 (
    echo.
    echo Build debug falhou.
    pause
    exit /b 1
)

echo.
echo Build debug concluido.
echo Executavel: dist\MVP-KCred-Debug.exe
echo.
echo Abra esse EXE para ver o erro no console caso a versao normal nao abra.
echo.
pause

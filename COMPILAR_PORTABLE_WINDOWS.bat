@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || goto :error
rmdir /s /q build 2>nul
rmdir /s /q dist\EvaluacionPersonalVoz 2>nul
".venv\Scripts\pyinstaller.exe" --noconfirm --clean --onedir --name EvaluacionPersonalVoz ^
  --add-data "app\templates;app\templates" ^
  --add-data "app\static;app\static" ^
  --add-data "assets;assets" ^
  main.py || goto :error

echo.
echo Compilacion terminada en dist\EvaluacionPersonalVoz
pause
exit /b 0
:error
echo [ERROR] La compilacion no termino correctamente.
pause
exit /b 1

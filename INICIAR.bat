@echo off
setlocal
cd /d "%~dp0"
title Evaluacion de Personal

where py >nul 2>nul
if errorlevel 1 (
  echo [ERROR] No se encontro Python. Instale Python 3.11, 3.12 o 3.13 de 64 bits.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno virtual local...
  py -3 -m venv .venv
  if errorlevel 1 goto :error
)

echo Iniciando aplicacion sin dependencias externas...
".venv\Scripts\python.exe" main.py
exit /b 0

:error
echo.
echo [ERROR] No se pudo iniciar. Revise los mensajes anteriores.
pause
exit /b 1

@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

cd /d "%ROOT%"

if not exist "%ROOT%\venv\Scripts\python.exe" (
  echo [ERROR] No existe el intérprete del venv. Ejecutá repair-venv.bat o creá venv a mano.
  pause
  exit /b 1
)

echo [Investment Radar] Backend: http://127.0.0.1:8000
call "%ROOT%\venv\Scripts\python.exe" -m uvicorn api.app:app --reload --host 127.0.0.1 --port 8000
echo.
pause
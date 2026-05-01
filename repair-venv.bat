@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

echo [Investment Radar] Reparando entorno Python en: "%ROOT%"

if not exist "%ROOT%\venv\Scripts\python.exe" (
  echo Creando venv...
  where py >nul 2>&1 && py -3.11 -m venv venv
  if errorlevel 1 python -m venv venv
  if not exist "%ROOT%\venv\Scripts\python.exe" (
    echo [ERROR] No se pudo crear venv. Instalá Python 3.11+ y reintentá.
    pause
    exit /b 1
  )
)

"%ROOT%\venv\Scripts\python.exe" -m pip install --upgrade pip
"%ROOT%\venv\Scripts\python.exe" -m pip install -r "%ROOT%\requirements.txt"

echo.
echo Verificando import del backend...
"%ROOT%\venv\Scripts\python.exe" -c "import api.app; print('OK: api.app carga bien.')" || (
  echo [ERROR] El import falló. Revisá mensajes arriba.
  pause
  exit /b 1
)

echo.
echo Listo. Podés usar start-local.bat o start-backend.bat / start-frontend.bat
pause
endlocal

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

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm no está en el PATH. Instalá Node.js LTS.
  pause
  exit /b 1
)

if not exist "%ROOT%\webapp\node_modules\" (
  echo [INFO] Instalando dependencias del frontend...
  pushd "%ROOT%\webapp"
  call npm install
  if errorlevel 1 (
    popd
    pause
    exit /b 1
  )
  popd
)

echo [INFO] Abriendo backend y frontend en ventanas separadas...
start "InvestmentRadar-API" "%ROOT%\start-backend.bat"
timeout /t 3 /nobreak >nul
start "InvestmentRadar-Web" "%ROOT%\start-frontend.bat"
timeout /t 8 /nobreak >nul

start "" "http://localhost:5173/"
echo.
echo Navegador abierto en http://localhost:5173/  ^(cerrá las ventanas API/Web para detener^).
endlocal
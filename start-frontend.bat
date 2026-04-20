@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

cd /d "%ROOT%\webapp"

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm no está en el PATH. Instalá Node.js LTS y reintentá.
  pause
  exit /b 1
)

if not exist "node_modules\" (
  echo [INFO] Primera vez: npm install...
  call npm install
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

echo [Investment Radar] Frontend: http://127.0.0.1:5173  ^(proxy /api -^> backend^)
call npm run dev
echo.
pause

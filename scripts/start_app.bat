@echo off
setlocal EnableExtensions
title Investment Radar Pro - inicio

rem Ir a la raíz del repo (este .bat vive en scripts\)
pushd "%~dp0.."
set "REPO_ROOT=%CD%"
popd

cd /d "%REPO_ROOT%" 2>nul
if errorlevel 1 (
  echo No se pudo acceder a la carpeta del proyecto: "%REPO_ROOT%"
  goto :end_error
)

echo ========================================
echo Investment Radar Pro
echo Raiz: %REPO_ROOT%
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No se encontro "python" en el PATH.
  echo Instala Python 3.10+ desde https://www.python.org/ y marca "Add to PATH".
  goto :end_error
)

if not exist "%REPO_ROOT%\venv\Scripts\activate.bat" (
  echo Creando entorno virtual venv...
  python -m venv "%REPO_ROOT%\venv"
  if errorlevel 1 (
    echo [ERROR] No se pudo crear venv. Proba: py -3.11 -m venv venv
    goto :end_error
  )
)

call "%REPO_ROOT%\venv\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] No se pudo activar venv.
  goto :end_error
)

echo Actualizando pip e instalando dependencias backend...
python -m pip install --upgrade pip
if errorlevel 1 goto :end_error

python -m pip install -r "%REPO_ROOT%\requirements.txt"
if errorlevel 1 goto :end_error

where npm >nul 2>&1
if errorlevel 1 (
  echo [ERROR] No se encontro "npm". Instala Node.js LTS desde https://nodejs.org/
  goto :end_error
)

if not exist "%REPO_ROOT%\webapp\node_modules\" (
  echo Instalando dependencias frontend ^(npm install^)...
  pushd "%REPO_ROOT%\webapp"
  call npm install
  if errorlevel 1 (
    popd
    echo [ERROR] npm install fallo.
    goto :end_error
  )
  popd
) else (
  echo node_modules ya existe; omitiendo npm install.
)

echo.
echo Abriendo backend en una ventana nueva...
start "Investment Radar API" cmd /k "cd /d ""%REPO_ROOT%"" && call ""%REPO_ROOT%\venv\Scripts\activate.bat"" && python -m uvicorn api.app:app --reload --host 127.0.0.1 --port 8000"

timeout /t 2 /nobreak >nul

echo Abriendo frontend en una ventana nueva...
start "Investment Radar Web" cmd /k "cd /d ""%REPO_ROOT%\webapp"" && npm run dev"

echo Esperando unos segundos a que Vite levante el servidor...
timeout /t 5 /nobreak >nul
echo Abriendo el panel en el navegador predeterminado...
start "" "http://localhost:5173"

echo.
echo Listo.
echo   Backend:  http://127.0.0.1:8000/docs
echo   Frontend: http://localhost:5173
echo.
echo Cerrá esta ventana cuando quieras; la API y el panel siguen en sus ventanas.
goto :end_ok

:end_error
echo.
echo Hubo un error. Revisa los mensajes arriba.
pause
exit /b 1

:end_ok
pause
endlocal
exit /b 0

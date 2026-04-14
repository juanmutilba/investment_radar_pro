@echo off

cd /d C:\Users\juanm\OneDrive\Escritorio\Juan\investment_radar_pro

echo Activando entorno...
call venv\Scripts\activate

echo Levantando backend...
start cmd /k python -m uvicorn api.app:app --reload

timeout /t 3 >nul

echo Levantando frontend...
cd webapp
start cmd /k npm run dev

timeout /t 5 >nul

echo Abriendo navegador...
start http://localhost:5173
@echo off
cd /d "C:\Users\juanm\OneDrive\Escritorio\Juan\investment_radar_pro"

call "venv\Scripts\activate.bat"

start /min "Backend" cmd /k "python -m uvicorn api.app:app --reload"
timeout /t 3 >nul

start /min "Frontend" cmd /k "cd /d C:\Users\juanm\OneDrive\Escritorio\Juan\investment_radar_pro\webapp && npm run dev"
timeout /t 5 >nul

start "" "http://localhost:5173"
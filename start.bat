@echo off
echo ========================================
echo       G13 Trading Bot - Demarrage
echo ========================================
echo.

cd /d "%~dp0backend"

echo Installation des dependances...
pip install -r requirements.txt

echo.
echo Demarrage du serveur...
echo API disponible sur: http://localhost:8000
echo Documentation: http://localhost:8000/docs
echo.

start "" http://localhost:8000
timeout /t 2 /nobreak >nul

python -m uvicorn main:app --host 0.0.0.0 --port 8000

pause

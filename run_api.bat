@echo off
title Sherpa 1099 - API Server
cd /d "T:\sherpa-1099"
echo ========================================
echo    Sherpa 1099 - API Server
echo ========================================
echo.
echo Starting server on http://0.0.0.0:8002
echo Employees can access at: http://taxwise-server:8002
echo.
echo Press Ctrl+C to stop the server
echo.

:: Use Python 3.12 directly (venv executables blocked on network drives)
py -3.12 -m uvicorn api.main:app --port 8002 --host 0.0.0.0
pause

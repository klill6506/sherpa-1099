@echo off
title Sherpa 1099 - API Server (HTTPS)
cd /d "C:\sherpa-1099"
echo ========================================
echo    Sherpa 1099 - API Server (HTTPS)
echo ========================================
echo.

:: Use the server's virtual environment
set VENV=C:\sherpa-1099\.venv\Scripts
set PYTHON=%VENV%\python.exe

:: Check if venv exists
if not exist "%PYTHON%" (
    echo ERROR: Virtual environment not found at %VENV%
    echo Please run: py -3.12 -m venv .venv
    echo Then run: .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: Check if SSL certificate exists
if not exist "certs\server.crt" (
    echo SSL certificate not found. Generating...
    "%PYTHON%" certs\generate_cert.py
    echo.
)

echo Starting HTTPS server on https://0.0.0.0:8002
echo Employees can access at: https://taxwise-server:8002
echo.
echo NOTE: Users will need to accept the self-signed certificate
echo       in their browser the first time they connect.
echo.
echo Press Ctrl+C to stop the server
echo.

:: Run uvicorn from the server's venv
"%PYTHON%" -m uvicorn api.main:app --port 8002 --host 0.0.0.0 --ssl-keyfile certs\server.key --ssl-certfile certs\server.crt
pause

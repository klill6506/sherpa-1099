@echo off
echo Starting Sherpa 1099 API on port 8002...
echo.
echo API Docs: http://127.0.0.1:8002/docs
echo.
cd /d "%~dp0"
py -3 -m uvicorn api.main:app --reload --port 8002 --host 127.0.0.1
pause

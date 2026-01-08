@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

echo ============================================
echo   Sherpa 1099 - Starting...
echo ============================================
echo.

REM --- Find Python via py launcher first ---
where py >nul 2>nul
IF %ERRORLEVEL% EQU 0 (
    set PY=py -3
) ELSE (
    where python >nul 2>nul
    IF %ERRORLEVEL% EQU 0 (
        set PY=python
    ) ELSE (
        echo [ERROR] Python not found on PATH.
        echo Please install Python 3.10+ from https://www.python.org/downloads/
        echo Make sure to check "Add to PATH" during installation.
        echo.
        pause
        exit /b 1
    )
)

echo [i] Using: %PY%
echo [i] Installing/updating dependencies...
%PY% -m pip install --user -r requirements.txt -q

echo.
echo [i] Starting Sherpa 1099 (FastAPI) on port 8002
echo [i] API Docs: http://127.0.0.1:8002/docs
echo [i] Press Ctrl+C to stop the server
echo.

REM --- Open browser after short delay ---
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8002"

%PY% -m uvicorn api.main:app --reload --port 8002 --host 127.0.0.1

pause

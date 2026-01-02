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

echo [i] Starting Sherpa 1099 (Streamlit) on port 8002
echo [i] Press Ctrl+C to stop the server
echo.
%PY% -m streamlit run app_streamlit_1099.py --server.port 8002

pause

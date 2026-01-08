@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

set LOG=sherpa_1099_log.txt
echo. > "%LOG%"
echo [i] Sherpa 1099 starting... > "%LOG%"
echo  - Folder: %CD% >> "%LOG%"
echo  - Timestamp: %DATE% %TIME% >> "%LOG%"
echo. >> "%LOG%"

REM --- Find Python via py launcher first ---
where py >nul 2>nul
IF %ERRORLEVEL% EQU 0 (
    set PY=py -3
) ELSE (
    where python >nul 2>nul
    IF %ERRORLEVEL% EQU 0 (
        set PY=python
    ) ELSE (
        echo [!] Python not found on PATH. >> "%LOG%"
        echo [!] Please install Python 3.10+ from https://www.python.org/downloads/ and check "Add to PATH". >> "%LOG%"
        type "%LOG%"
        echo.
        echo Press any key to exit...
        pause >nul
        exit /b 1
    )
)

echo [i] Using interpreter: %PY% >> "%LOG%"
echo [i] Upgrading pip and installing requirements (user site-packages)... >> "%LOG%"
%PY% -m pip install --upgrade pip --user >> "%LOG%" 2>&1
IF %ERRORLEVEL% NEQ 0 goto :pip_fail

%PY% -m pip install --user -r requirements.txt >> "%LOG%" 2>&1
IF %ERRORLEVEL% NEQ 0 goto :pip_fail

echo [i] Launching FastAPI app on port 8002... >> "%LOG%"
echo.
echo ============================================
echo   Sherpa 1099 - FastAPI Backend
echo ============================================
echo   URL: http://127.0.0.1:8002
echo   API Docs: http://127.0.0.1:8002/docs
echo   Press Ctrl+C to stop
echo ============================================
echo.

REM --- Open browser after short delay ---
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8002"

%PY% -m uvicorn api.main:app --reload --port 8002 --host 127.0.0.1 >> "%LOG%" 2>&1
set CODE=%ERRORLEVEL%

echo. >> "%LOG%"
echo [i] FastAPI exited with code %CODE% >> "%LOG%"
type "%LOG%"
echo.
echo Press any key to close...
pause >nul
exit /b %CODE%

:pip_fail
echo [!] pip/requirements step failed. See log below. >> "%LOG%"
type "%LOG%"
echo.
echo Press any key to close...
pause >nul
exit /b 1

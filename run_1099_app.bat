
@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
cd /d "%~dp0"

set LOG=slipstream_log.txt
echo. > "%LOG%"
echo [i] Slipstream 1099 starting... > "%LOG%"
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

echo [i] Launching app... >> "%LOG%"
%PY% -m streamlit run "app_streamlit_1099.py" >> "%LOG%" 2>&1
set CODE=%ERRORLEVEL%

echo. >> "%LOG%"
echo [i] Streamlit exited with code %CODE% >> "%LOG%"
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
%PY% -m streamlit run "app_streamlit_1099.py" --server.port 8503 --server.address 0.0.0.0
pause
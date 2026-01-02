
@echo off
SETLOCAL ENABLEDELAYEDEXPANSION
cd /d "%~dp0"
echo.
echo === Slipstream 1099 DEBUG MODE ===
echo This will show live output. Leave this window open.
echo.

where py >nul 2>nul
IF %ERRORLEVEL% EQU 0 (
    set PY=py -3
) ELSE (
    where python >nul 2>nul
    IF %ERRORLEVEL% EQU 0 (
        set PY=python
    ) ELSE (
        echo [!] Python not found. Install Python 3.10+ and try again.
        cmd /k
        exit /b 1
    )
)

echo [i] Upgrading pip and installing requirements...
%PY% -m pip install --upgrade pip --user
%PY% -m pip install --user -r requirements.txt

echo.
echo [i] Launching app...
%PY% -m streamlit run "app_streamlit_1099.py"
echo.
echo [i] Streamlit exited. Press any key to leave this window open, or close it now.
pause >nul
cmd /k

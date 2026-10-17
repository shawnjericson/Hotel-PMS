@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        py -3 -X utf8 main.py
        goto :finished
    )
)
where python >nul 2>nul
if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
    if not errorlevel 1 (
        python -X utf8 main.py
        goto :finished
    )
)
echo Python 3.10 or newer is required.
echo Install Python and try again.
pause
exit /b 1
:finished
if errorlevel 1 (
    echo The application stopped with an error. See the message above.
    pause
    exit /b 1
)
endlocal

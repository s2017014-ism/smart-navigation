@echo off
setlocal
if not exist "%~dp0backend\main.py" (
    echo Backend files are missing. Download and extract the complete
    echo smart-navigation-backend-launcher-windows.zip from the release.
    pause
    exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File "%~dp0start_backend.ps1"
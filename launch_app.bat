@echo off
setlocal EnableDelayedExpansion

set "PROJECT_DIR=%~dp0"
set "FRONTEND_DIR=%PROJECT_DIR%frontend"
set "FLUTTER=%USERPROFILE%\flutter\bin\flutter.bat"
set "FLUTTER_FROM_PATH="
set "ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
set "EMULATOR=%LOCALAPPDATA%\Android\Sdk\emulator\emulator.exe"
set "AVD_NAME="

if not exist "%FLUTTER%" (
    for /f "delims=" %%F in ('where flutter 2^>nul') do if not defined FLUTTER_FROM_PATH set "FLUTTER_FROM_PATH=%%F"
    if defined FLUTTER_FROM_PATH set "FLUTTER=!FLUTTER_FROM_PATH!"
)

if not exist "%FRONTEND_DIR%\pubspec.yaml" (
    echo Cannot find the Flutter app at "%FRONTEND_DIR%".
    pause
    exit /b 1
)

if not exist "%FLUTTER%" (
    echo Flutter was not found. Install Flutter or add it to PATH.
    pause
    exit /b 1
)

echo Checking the backend...
curl.exe --silent --fail http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    echo Starting backend in a separate window...
    start "Macau Navigation Backend" /D "%PROJECT_DIR%" cmd.exe /k python -m uvicorn main:app --host 0.0.0.0 --port 8000
    set /a ATTEMPTS=0
    :wait_backend
    timeout /t 1 /nobreak >nul
    curl.exe --silent --fail http://localhost:8000/health >nul 2>&1
    if not errorlevel 1 goto backend_ready
    set /a ATTEMPTS+=1
    if !ATTEMPTS! lss 30 goto wait_backend
    echo Backend did not become ready. Check the backend window for errors.
    pause
    exit /b 1
)

:backend_ready
echo Backend is ready.

if exist "%ADB%" (
    "%ADB%" start-server >nul
    "%ADB%" devices | findstr /c:"emulator-" | findstr /c:"device" >nul
    if errorlevel 1 (
        if exist "%EMULATOR%" (
            for /f "usebackq delims=" %%A in (`"%EMULATOR%" -list-avds`) do if not defined AVD_NAME set "AVD_NAME=%%A"
            if defined AVD_NAME (
                echo Starting Android emulator "!AVD_NAME!"...
                start "Android Emulator" "%EMULATOR%" -avd "!AVD_NAME!"
                "%ADB%" wait-for-device
                set /a BOOT_ATTEMPTS=0
                :wait_emulator
                "%ADB%" shell getprop sys.boot_completed 2>nul | findstr "1" >nul
                if not errorlevel 1 goto emulator_ready
                timeout /t 2 /nobreak >nul
                set /a BOOT_ATTEMPTS+=1
                if !BOOT_ATTEMPTS! lss 90 goto wait_emulator
                echo The emulator did not finish booting.
                pause
                exit /b 1
            )
        )
    )
)

:emulator_ready
echo Preparing Flutter packages...
cd /d "%FRONTEND_DIR%"
call "%FLUTTER%" pub get
if errorlevel 1 (
    echo Flutter package setup failed.
    pause
    exit /b 1
)

echo Launching Macau Navigation on the Android emulator...
call "%FLUTTER%" run -d emulator-5554
if errorlevel 1 (
    echo App launch failed. Check Flutter and emulator setup.
    pause
    exit /b 1
)

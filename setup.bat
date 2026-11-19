@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo   Gesture Recognition - Environment Setup
echo ==========================================
echo.
echo This window will remain open after setup.
echo Do not close it while dependencies are installing.
echo.

where powershell.exe >nul 2>nul
if errorlevel 1 (
    echo ERROR: Windows PowerShell (powershell.exe) was not found.
    echo Please use Windows PowerShell 5.1 or later.
    echo.
    pause
    exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -NoPause
set "SETUP_EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%SETUP_EXIT_CODE%"=="0" (
    echo Setup process returned exit code %SETUP_EXIT_CODE%.
    echo Check setup.log in this folder for detailed output.
) else (
    echo Setup process finished. If the message above says SETUP FAILED,
    echo check setup.log in this folder for the actual error.
)
echo.
pause
exit /b %SETUP_EXIT_CODE%

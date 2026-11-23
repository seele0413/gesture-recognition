@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo Portable runtime not found. Use the complete Windows release ZIP.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" -I -X utf8 "%~dp0launcher.py" --check-vision
set "APP_EXIT=%ERRORLEVEL%"
pause
exit /b %APP_EXIT%

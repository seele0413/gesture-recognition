@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python.exe" (
  echo Portable runtime not found. Extract the Windows release ZIP completely.
  echo For the source package use setup.ps1 and run.ps1.
  pause
  exit /b 1
)
"%~dp0runtime\python.exe" -I -X utf8 "%~dp0launcher.py" %*
set "APP_EXIT=%ERRORLEVEL%"
if not "%APP_EXIT%"=="0" pause
exit /b %APP_EXIT%

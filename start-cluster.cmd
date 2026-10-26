@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup-local.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m scripts.cluster --open-browser
if errorlevel 1 pause

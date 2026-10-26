@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.k8s_wsl open
if errorlevel 1 pause

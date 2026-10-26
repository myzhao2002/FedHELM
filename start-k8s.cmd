@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.k8s_wsl up
set "k8s_exit=%errorlevel%"
if not "%k8s_exit%"=="0" echo Kubernetes startup failed. Keep this message for troubleshooting.
pause
exit /b %k8s_exit%

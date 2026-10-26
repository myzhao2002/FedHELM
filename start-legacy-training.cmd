@echo off
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m scripts.local --open-browser --reuse-existing --workload-backend process --training-backend torch --base-port 14000 --data-dir runtime/training
set "training_exit=%errorlevel%"
if not "%training_exit%"=="0" echo Startup failed. Keep this message for troubleshooting.
pause
exit /b %training_exit%

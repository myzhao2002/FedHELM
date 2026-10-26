@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.training.txt
if errorlevel 1 goto failed
echo Setup complete. Run start-cluster.cmd
pause
exit /b 0
:failed
echo Setup failed. Check the error above and Python 3.12 installation.
pause
exit /b 1

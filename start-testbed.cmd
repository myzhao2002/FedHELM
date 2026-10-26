@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto invalid
".venv\Scripts\python.exe" -c "import sys,ssl; assert sys.version_info[:2] == (3,12); import fastapi,httpx,pydantic"
if errorlevel 1 goto invalid
".venv\Scripts\python.exe" -m scripts.local --open-browser --reuse-existing --workload-backend process --data-dir runtime/testbed
set "testbed_exit=%errorlevel%"
if not "%testbed_exit%"=="0" echo Startup failed. Please keep this message.
pause
exit /b %testbed_exit%
:invalid
echo Project Python is invalid. See README.md.
pause
exit /b 1

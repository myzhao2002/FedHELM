@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -c "import sys,ssl; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'; import fastapi,httpx,pydantic"
if errorlevel 1 goto invalid
".venv\Scripts\python.exe" -m scripts.local --demo
set "demo_exit=%errorlevel%"
goto finish
:missing
echo Project virtual environment is missing. See README.md.
set "demo_exit=1"
goto finish
:invalid
echo Project Python is invalid. Do not recreate it with the default Anaconda python.
echo See the Windows troubleshooting section in README.md.
set "demo_exit=1"
:finish
if not "%~1"=="--no-pause" pause
exit /b %demo_exit%

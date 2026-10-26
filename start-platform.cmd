@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto invalid
".venv\Scripts\python.exe" -c "import sys,ssl; assert sys.version_info[:2] == (3,12), 'Python 3.12 required'; import fastapi,httpx,pydantic"
if errorlevel 1 goto invalid
".venv\Scripts\python.exe" -m scripts.local --open-browser --reuse-existing
set "platform_exit=%errorlevel%"
if not "%platform_exit%"=="0" echo Startup failed. Please keep this message or send a screenshot.
echo.
echo If a console was already running, it has been opened in your browser.
pause
exit /b %platform_exit%
:invalid
echo Project Python is missing or invalid. See README.md.
pause
exit /b 1

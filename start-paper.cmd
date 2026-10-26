@echo off
cd /d "%~dp0"
set PAPER_PROFILE=1
set AUTO_MONITOR=1
if not defined VALIDATION_SECONDS set VALIDATION_SECONDS=3
".venv\Scripts\python.exe" -m scripts.local --workload-backend process --training-backend torch --base-port 15000 --data-dir runtime/paper --open-browser --reuse-existing
if errorlevel 1 pause

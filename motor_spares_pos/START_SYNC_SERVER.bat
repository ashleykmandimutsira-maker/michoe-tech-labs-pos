@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" sync_server.py
) else (
    py -3 sync_server.py
)
endlocal

@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Virtual environment .venv was not found.
    echo Run the installation command from README.md first.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" run_server.py

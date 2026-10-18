@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
set "PYTHON_ARGS="
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  set "PYTHON_EXE=py"
  set "PYTHON_ARGS=-3.11"
)

if not defined PYTHON_EXE (
  echo Python 3.11 was not found. Trying to install it with winget...
  where winget >nul 2>&1
  if errorlevel 1 goto :python_not_found
  winget install --id Python.Python.3.11 --exact --silent --accept-package-agreements --accept-source-agreements
  if errorlevel 1 goto :python_not_found
  py -3.11 -c "import sys" >nul 2>&1
  if not errorlevel 1 (
    set "PYTHON_EXE=py"
    set "PYTHON_ARGS=-3.11"
  )
)

if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python311\python.exe" set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON_EXE if exist "%ProgramFiles%\Python311\python.exe" set "PYTHON_EXE=%ProgramFiles%\Python311\python.exe"
if not defined PYTHON_EXE goto :python_not_found

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment and installing dependencies...
  "%PYTHON_EXE%" %PYTHON_ARGS% -m venv .venv
  if errorlevel 1 goto :setup_error
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  if errorlevel 1 goto :setup_error
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto :setup_error
  ".venv\Scripts\python.exe" -m spacy download en_core_web_sm
  if errorlevel 1 goto :setup_error
  ".venv\Scripts\python.exe" -m spacy download de_core_news_sm
  if errorlevel 1 goto :setup_error
)

set "LINGUAFLOW_HOST=127.0.0.1"
set "LINGUAFLOW_PORT=8001"
set "TRANSLATION_WORKSPACE=C:\ai_trans_2_0"
echo Starting LinguaFlow 2.0 at http://%LINGUAFLOW_HOST%:%LINGUAFLOW_PORT%
".venv\Scripts\python.exe" run_server.py
exit /b %errorlevel%

:setup_error
echo.
echo Setup failed. Check that Python 3.11, internet access, and pip are available.
pause
exit /b 1

:python_not_found
echo.
echo Python 3.11 could not be installed automatically.
echo Install it from https://www.python.org/downloads/ or ask the system administrator, then run this file again.
pause
exit /b 1

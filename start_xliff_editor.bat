@echo off
setlocal

rem Launch the standalone XLIFF editor (FastAPI + Vite).
set "ROOT=%~dp0"
set "EDITOR=%ROOT%xliff-editor"

if not exist "%EDITOR%\backend\app\main.py" (
  echo XLIFF Editor was not found: "%EDITOR%"
  pause
  exit /b 1
)

if exist "%EDITOR%\.venv\Scripts\python.exe" (
  set "PYTHON=%EDITOR%\.venv\Scripts\python.exe"
) else if exist "%ROOT%.venv\Scripts\python.exe" (
  set "PYTHON=%ROOT%.venv\Scripts\python.exe"
) else (
  echo Python virtual environment was not found.
  echo Create one with: py -3.12 -m venv xliff-editor\.venv
  pause
  exit /b 1
)

if not exist "%EDITOR%\frontend\node_modules" (
  echo Installing frontend dependencies...
  pushd "%EDITOR%\frontend"
  call npm install
  if errorlevel 1 (
    popd
    echo Failed to install frontend dependencies.
    pause
    exit /b 1
  )
  popd
)

echo Starting XLIFF Editor API at http://127.0.0.1:8001 ...
start "XLIFF Editor API" /min /D "%EDITOR%" "%PYTHON%" -m uvicorn app.main:app --app-dir backend --port 8001

echo Starting XLIFF Editor UI at http://127.0.0.1:5173 ...
start "XLIFF Editor UI" /D "%EDITOR%\frontend" npm.cmd run dev -- --host 127.0.0.1

timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:5173"
endlocal

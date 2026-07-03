@echo off
rem Grain Size Analyzer - Windows launcher.
rem First run creates a virtual environment and installs dependencies;
rem after that it just starts the app. Requires Python 3.11+ from python.org
rem (tick "Add python.exe to PATH" during setup).
setlocal
cd /d "%~dp0"

set "PY="
where py >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/ and tick
  echo "Add python.exe to PATH" during setup, then run this again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv
  if errorlevel 1 (echo Could not create the virtual environment. & pause & exit /b 1)
  echo Installing dependencies...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (echo Dependency install failed. & pause & exit /b 1)
)

echo.
echo Starting Grain Size Analyzer at http://localhost:5066
echo Press Ctrl+C to stop the server.
start "" cmd /c "timeout /t 3 >nul & start http://localhost:5066"
".venv\Scripts\python.exe" app.py
pause

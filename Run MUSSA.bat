@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%~dp0
if exist "%~dp0.venv\Scripts\python.exe" (set PY="%~dp0.venv\Scripts\python.exe") else (where python >nul 2>nul && (set PY=python) || (set PY=py -3))
echo Starting MUSSA... the app window opens in a few seconds.
echo Keep this window open while you use the app. Close it to quit.
%PY% -m cagsyntax.app
if errorlevel 1 (
  echo.
  echo MUSSA could not start. The error is shown above.
  pause
)

@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%~dp0
where python >nul 2>nul && (set PY=python) || (set PY=py -3)
%PY% -m cagsyntax.app
if errorlevel 1 (
  echo.
  echo MUSSA could not start. The error is shown above.
  pause
)

@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0src;%~dp0
where pythonw >nul 2>nul && (start "" pythonw -m cagsyntax.app) || (python -m cagsyntax.app)

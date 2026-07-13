@echo off
setlocal
set "REPO_ROOT=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_ROOT%scripts\start-trading-assistant.ps1"
endlocal

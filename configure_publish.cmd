@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0save_publish_token.ps1"
if errorlevel 1 (
  echo Setup failed. Check the error above.
) else (
  echo GitHub publishing is configured.
)
pause

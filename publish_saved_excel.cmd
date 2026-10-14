@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_daily_update.ps1" -UseSavedExcel
if errorlevel 1 (
  echo Publication failed. See daily-site-update.log in the project folder.
) else (
  echo Publication finished. Check GitHub and the website for the new data date.
)
pause

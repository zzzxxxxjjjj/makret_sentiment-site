@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo Updating Wind, RQData and verifying short/medium-term synthesis...
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" -X utf8 daily_site_update.py --refresh-excel > daily-site-update.log 2>&1
type daily-site-update.log
if errorlevel 1 echo Some stages failed. Check daily-update-status.json; existing values and actual dates remain visible.
netstat -ano | findstr /R /C:":8876 .*LISTENING" >nul
if not errorlevel 1 (
  echo Dashboard is already running at http://127.0.0.1:8876/
  pause
  exit /b 0
)
set ENABLE_RQDATA_REFRESH=0
"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -X utf8 server.py

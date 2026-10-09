@echo off
setlocal
cd /d "%~dp0"
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" rqdata_breadth_refresh.py --output rqdata-breadth-sentiment.json --start 2018-01-01
if errorlevel 1 (
  echo.
  echo RQData breadth refresh failed. Check the RQData login and network, then retry.
  pause
  exit /b 1
)
echo.
echo RQData breadth cache refreshed. Reload the dashboard to use the exact breadth series.
pause

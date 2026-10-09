@echo off
setlocal
cd /d "%~dp0"
echo [1/7] Updating RQData turnover, MA100 distance, financing, Land Stock Connect MA20, new equity funds and concentration...
echo The first run backfills the latest five years; later runs only add missing dates.
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" rqdata_refresh.py --output rqdata-broad-sentiment.json > rqdata-update.log 2>&1
set "RQDATA_EXIT=%ERRORLEVEL%"
type rqdata-update.log
if not "%RQDATA_EXIT%"=="0" (
  echo.
  echo RQData market-data update failed. The dashboard will continue with the last local cache.
)
echo.
echo [2/7] Updating RQData breadth history for the daily 20-day sentiment cycle...
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" rqdata_breadth_refresh.py --output rqdata-breadth-sentiment.json --start 2018-01-01
if errorlevel 1 (
  echo.
  echo RQData breadth update failed. The dashboard will continue with the last local cache.
)
echo.
echo [3/7] Updating CITICS level-1 industry capital flows and crowding...
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" rqdata_industry_refresh.py --output rqdata-industry-sentiment.json
if errorlevel 1 (
  echo.
  echo Industry capital-flow update failed. The page will continue with the last local cache.
)
echo.
echo [4/7] Updating CITICS level-2 industry active capital-flow children...
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" rqdata_second_industry_flow_refresh.py --output rqdata-industry-sentiment.json
if errorlevel 1 (
  echo.
  echo Level-2 industry capital-flow update failed. The page will continue with the last local children cache.
)
echo.
echo [5/7] Updating five-year stock-fund position history...
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" rqdata_fund_position_refresh.py --output rqdata-fund-stock-position-history.json --start 2021-07-01
if errorlevel 1 (
  echo.
  echo Fund-position history update failed. The page will continue with Excel snapshots and the last local history.
)
echo.
echo [6/7] Refreshing the three Excel/Wind workbooks and rebuilding macro tracking data...
"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" macro_tracking_refresh.py --output macro-tracking.json --refresh-excel
if errorlevel 1 (
  echo.
  echo Macro tracking update failed. The page will continue with the last local cache.
)
echo.
echo [7/7] Starting the dashboard at http://127.0.0.1:8876/
netstat -ano | findstr /R /C:":8876 .*LISTENING" >nul
if not errorlevel 1 (
  echo The old dashboard process is still running.
  echo Close its command window, then double-click this file again so the new page code can load.
  pause
  exit /b 0
)
echo Keep this window open while using the dashboard.
set ENABLE_RQDATA_REFRESH=0
"C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" server.py

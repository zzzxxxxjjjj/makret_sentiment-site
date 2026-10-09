@echo off
cd /d "%~dp0"
"C:\Users\DELL\anaconda3\envs\rqsdk\python.exe" rqdata_second_industry_flow_refresh.py --output rqdata-industry-sentiment.json
pause

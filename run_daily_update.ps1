$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ((Get-Date).DayOfWeek -in @('Saturday','Sunday')) { exit 0 }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = 'C:\Users\DELL\anaconda3\envs\rqsdk\python.exe'
& $python -X utf8 "$PSScriptRoot/daily_site_update.py" --refresh-excel *> "$PSScriptRoot/daily-site-update.log"
exit $LASTEXITCODE

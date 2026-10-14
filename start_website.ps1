$ErrorActionPreference = "Stop"

$Python = "C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$RqPython = "C:\Users\DELL\anaconda3\envs\rqsdk\python.exe"
$SiteDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:ENABLE_RQDATA_REFRESH = "0"

Write-Host "Starting Excel market sentiment site..."
Write-Host "Open: http://127.0.0.1:8876"
Write-Host "Keep this PowerShell window open."

Set-Location $SiteDir
Write-Host "Refreshing Excel, RQData and short/medium-term sentiment..."
try {
  & $RqPython -X utf8 ".\daily_site_update.py" --refresh-excel
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Daily refresh failed. Check daily-update-status.json for the actual source and synthesis dates."
  }
} catch {
  Write-Host "Daily refresh failed. The site retains saved values and their actual dates."
}
Write-Host "RQData is read from the local cache after startup."
& $Python ".\server.py"

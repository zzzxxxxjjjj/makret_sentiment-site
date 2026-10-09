$ErrorActionPreference = "Stop"

$Python = "C:\Users\DELL\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$RqPython = "C:\Users\DELL\anaconda3\envs\rqsdk\python.exe"
$SiteDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$env:ENABLE_RQDATA_REFRESH = "0"

Write-Host "Starting Excel market sentiment site..."
Write-Host "Open: http://127.0.0.1:8876"
Write-Host "Keep this PowerShell window open."

Set-Location $SiteDir
Write-Host "Refreshing CITICS level-2 industry stock-flow leaders..."
try {
  & $RqPython ".\rqdata_second_industry_flow_refresh.py" --output ".\rqdata-industry-sentiment.json"
  if ($LASTEXITCODE -ne 0) {
    Write-Host "Level-2 industry refresh failed. The site will continue with the last local cache."
  }
} catch {
  Write-Host "Level-2 industry refresh failed. The site will continue with the last local cache."
}
Write-Host "RQData is read from the local cache after startup."
& $Python ".\server.py"

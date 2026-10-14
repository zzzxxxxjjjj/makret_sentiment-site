$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if ((Get-Date).DayOfWeek -in @('Saturday','Sunday')) { exit 0 }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$python = 'C:\Users\DELL\anaconda3\envs\rqsdk\python.exe'
$tokenPath = Join-Path $env:LOCALAPPDATA 'MarketSentiment\github-token.dpapi'
if (-not (Test-Path -LiteralPath $tokenPath)) { throw 'GitHub publishing credential is missing; run save_publish_token.ps1 as this Windows user' }
$secure = Get-Content -LiteralPath $tokenPath -Raw | ConvertTo-SecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:GITHUB_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
try {
  & $python -X utf8 "$PSScriptRoot/publish_daily_snapshot.py" --check-auth *> "$PSScriptRoot/daily-site-update.log"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $python -X utf8 "$PSScriptRoot/daily_site_update.py" --refresh-excel *>> "$PSScriptRoot/daily-site-update.log"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $python -X utf8 "$PSScriptRoot/publish_daily_snapshot.py" *>> "$PSScriptRoot/daily-site-update.log"
  exit $LASTEXITCODE
} finally {
  Remove-Item Env:GITHUB_TOKEN -ErrorAction SilentlyContinue
}

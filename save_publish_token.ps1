$ErrorActionPreference = 'Stop'
$directory = Join-Path $env:LOCALAPPDATA 'MarketSentiment'
New-Item -ItemType Directory -Path $directory -Force | Out-Null
$path = Join-Path $directory 'github-token.dpapi'
$token = Read-Host 'Enter a GitHub fine-grained token with Contents read/write for zzzxxxxjjjj/makret_sentiment-site' -AsSecureString
$token | ConvertFrom-SecureString | Set-Content -LiteralPath $path -NoNewline
Write-Output "Credential saved for the current Windows user at $path"
$taskName = 'MarketSentiment-Publish-Saved-Excel'
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
  Enable-ScheduledTask -TaskName $taskName | Out-Null
  Write-Output 'Morning publication task enabled.'
}

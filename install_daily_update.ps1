$ErrorActionPreference = 'Stop'
$taskName = 'MarketSentiment-Publish-Saved-Excel'
$runner = Join-Path $PSScriptRoot 'run_daily_update.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw 'Daily update runner is missing' }
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Actions.Arguments -notlike "*$runner*") { throw 'Task name belongs to a different project' }
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '" -UseSavedExcel'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $PSScriptRoot
$triggers = @(New-ScheduledTaskTrigger -Daily -At '10:45'; New-ScheduledTaskTrigger -Daily -At '11:45')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Force | Select-Object TaskName,State
if (-not (Test-Path -LiteralPath (Join-Path $env:LOCALAPPDATA 'MarketSentiment\github-token.dpapi'))) {
  Disable-ScheduledTask -TaskName $taskName | Out-Null
  Write-Output 'Task installed but disabled until save_publish_token.ps1 configures publishing.'
}

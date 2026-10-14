$ErrorActionPreference = 'Stop'
$taskName = 'MarketSentiment-Wind-RQData-Daily'
$runner = Join-Path $PSScriptRoot 'run_daily_update.ps1'
if (-not (Test-Path -LiteralPath $runner)) { throw 'Daily update runner is missing' }
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Actions.Arguments -notlike "*$runner*") { throw 'Task name belongs to a different project' }
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $PSScriptRoot
$triggers = @(New-ScheduledTaskTrigger -Daily -At '18:37'; New-ScheduledTaskTrigger -Daily -At '20:37'; New-ScheduledTaskTrigger -Daily -At '22:37')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Force | Select-Object TaskName,State

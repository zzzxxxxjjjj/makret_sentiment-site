param(
  [Parameter(Mandatory = $true)][string]$MarketWorkbook,
  [Parameter(Mandatory = $true)][string]$CreditWorkbook,
  [Parameter(Mandatory = $true)][string]$FxWorkbook,
  [int]$MinimumWaitSeconds = 20,
  [int]$MaximumWaitSeconds = 120
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Refresh-Workbook {
  param(
    [Parameter(Mandatory = $true)]$Excel,
    [Parameter(Mandatory = $true)][string]$Path
  )

  if (-not (Test-Path -LiteralPath $Path)) {
    throw "未找到Excel文件：$Path"
  }

  Write-Host "正在自动刷新：$Path"
  $book = $null
  try {
    $book = $Excel.Workbooks.Open($Path, 3, $false)
    if ($book.ReadOnly) {
      throw "文件以只读方式打开，无法保存更新：$Path"
    }
    $book.RefreshAll()
    try { $Excel.CalculateFullRebuild() } catch {}
    try { $Excel.CalculateUntilAsyncQueriesDone() } catch {}

    $started = Get-Date
    do {
      Start-Sleep -Seconds 2
      try { $Excel.Calculate() } catch {}
      $elapsed = ((Get-Date) - $started).TotalSeconds
      $calculationDone = $Excel.CalculationState -eq 0
    } while ($elapsed -lt $MinimumWaitSeconds -or (-not $calculationDone -and $elapsed -lt $MaximumWaitSeconds))

    $book.Save()
    Write-Host "刷新并保存完成：$Path"
  }
  finally {
    if ($null -ne $book) {
      try { $book.Close($true) } catch {}
      [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book)
    }
  }
}

$excel = $null
$failures = @()
try {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $true
  $excel.WindowState = 2
  $excel.DisplayAlerts = $false
  $excel.AskToUpdateLinks = $false
  try { $excel.RTD.ThrottleInterval = 1000 } catch {}

  foreach ($path in @($MarketWorkbook, $CreditWorkbook, $FxWorkbook)) {
    try {
      Refresh-Workbook -Excel $excel -Path $path
    }
    catch {
      $failures += $_.Exception.Message
      Write-Warning $_.Exception.Message
    }
  }
}
finally {
  if ($null -ne $excel) {
    try { $excel.Quit() } catch {}
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}

if ($failures.Count -gt 0) {
  exit 1
}

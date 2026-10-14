param(
  [string]$MarketWorkbook,
  [string]$CreditWorkbook,
  [string]$FxWorkbook,
  [string[]]$WorkbookPaths,
  [string]$WindAddIn = 'C:\Wind\Wind.NET.Client\WindNET\DataBrowse\XLA\WindFunc.xla',
  [int]$MinimumWaitSeconds = 20,
  [int]$MaximumWaitSeconds = 120
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$paths = @($WorkbookPaths) + @($MarketWorkbook, $CreditWorkbook, $FxWorkbook)
$paths = @($paths | Where-Object { $_ } | Select-Object -Unique)
if (-not $paths.Count) { throw 'No Excel workbooks specified' }
$excel = $null
$ownsExcel = $false
$failures = @()
try {
  try { $excel = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application') } catch {}
  if ($null -eq $excel) {
    $excel = New-Object -ComObject Excel.Application
    $ownsExcel = $true
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
  }
  if (-not (Test-Path -LiteralPath $WindAddIn)) { throw 'Installed Wind Excel add-in not found' }
  $windBook = @($excel.Workbooks | Where-Object { $_.FullName -eq $WindAddIn })
  if (-not $windBook.Count) { $null = $excel.Workbooks.Open($WindAddIn, 0, $true) }
  try { $excel.RTD.ThrottleInterval = 1000 } catch {}
  foreach ($path in $paths) {
    $book = $null
    $openedHere = $false
    try {
      if (-not (Test-Path -LiteralPath $path)) { throw 'Source workbook not found' }
      $resolved = (Resolve-Path -LiteralPath $path).Path
      $book = @($excel.Workbooks | Where-Object { $_.FullName -eq $resolved }) | Select-Object -First 1
      if ($null -eq $book) { $book = $excel.Workbooks.Open($resolved, 3, $false); $openedHere = $true }
      if ($book.ReadOnly) { throw 'Source workbook is read-only' }
      $book.RefreshAll()
      $excel.CalculateFullRebuild()
      $started = Get-Date
      do {
        Start-Sleep -Seconds 2
        $excel.Calculate()
        $elapsed = ((Get-Date) - $started).TotalSeconds
        $done = $excel.CalculationState -eq 0
      } while ($elapsed -lt $MinimumWaitSeconds -or (-not $done -and $elapsed -lt $MaximumWaitSeconds))
      if (-not $done) { throw 'Excel refresh timed out; previous saved workbook retained' }
      foreach ($sheet in $book.Worksheets) {
        $formulaErrors = $null
        try { $formulaErrors = $sheet.UsedRange.SpecialCells(-4123, 16) } catch {}
        if ($null -ne $formulaErrors) { throw 'Wind/Excel formulas returned errors; previous saved workbook retained' }
      }
      $book.Save()
      Write-Output ('Refreshed and saved: ' + [IO.Path]::GetFileName($resolved))
    } catch {
      $failures += $_.Exception.Message
      Write-Warning $_.Exception.Message
    } finally {
      if ($null -ne $book -and $openedHere) { $book.Close($false) }
      if ($null -ne $book) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($book) }
    }
  }
} finally {
  if ($null -ne $excel) {
    $windBook = $null
    if ($ownsExcel) { $excel.Quit() }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
  }
  [GC]::Collect()
  [GC]::WaitForPendingFinalizers()
}
if ($failures.Count) { exit 1 }

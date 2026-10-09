param(
  [Parameter(Mandatory = $true)]
  [string]$WorkbookPath
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Read-RangeRows($Worksheet, $Address) {
  $range = $Worksheet.Range($Address)
  $values = $range.Value2
  $rows = @()

  for ($r = 1; $r -le $range.Rows.Count; $r++) {
    $row = @()
    for ($c = 1; $c -le $range.Columns.Count; $c++) {
      $row += $values[$r, $c]
    }
    $rows += ,$row
  }
  return $rows
}

$excel = [Runtime.InteropServices.Marshal]::GetActiveObject("Excel.Application")

try {
  # Excel usually defaults to 2000 ms. Wind RTD still controls whether a cell has a fresh value.
  $excel.RTD.ThrottleInterval = 1000
} catch {}

$targetFullName = [System.IO.Path]::GetFullPath($WorkbookPath)
$targetName = [System.IO.Path]::GetFileName($WorkbookPath)
$workbook = $null

foreach ($book in $excel.Workbooks) {
  try {
    $bookFullName = [System.IO.Path]::GetFullPath($book.FullName)
    if ($bookFullName -eq $targetFullName -or $book.Name -eq $targetName) {
      $workbook = $book
      break
    }
  } catch {
    if ($book.Name -eq $targetName) {
      $workbook = $book
      break
    }
  }
}

if ($null -eq $workbook) {
  throw "Workbook is not open in Excel: $WorkbookPath"
}

$payload = [ordered]@{
  workbookName = $workbook.Name
  dashboardRows = Read-RangeRows $workbook.Worksheets.Item("Sheet4") "F4:K17"
  industryRows = Read-RangeRows $workbook.Worksheets.Item(3) "A1:J32"
}

$payload | ConvertTo-Json -Depth 8 -Compress

param(
  [string]$PythonExe = "python",
  [string]$ConfigPath = "",
  [switch]$RunOnce,
  [switch]$ForceRun
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDir

if (-not $ConfigPath) {
  $ConfigPath = Join-Path $projectRoot "config.local.yaml"
}

if (-not (Test-Path $ConfigPath)) {
  throw "Config file not found: $ConfigPath"
}

function Read-CstDate {
  param(
    [string]$Prompt,
    [string]$DefaultValue
  )

  while ($true) {
    $inputValue = Read-Host "$Prompt [$DefaultValue]"
    if ([string]::IsNullOrWhiteSpace($inputValue)) {
      $inputValue = $DefaultValue
    }

    try {
      [void][datetime]::ParseExact(
        $inputValue,
        "yyyy-MM-dd",
        [System.Globalization.CultureInfo]::InvariantCulture,
        [System.Globalization.DateTimeStyles]::None
      )
      return $inputValue
    } catch {
      Write-Host "Invalid date format: $inputValue (expected YYYY-MM-DD)" -ForegroundColor Yellow
    }
  }
}

$defaultEnd = (Get-Date).ToString("yyyy-MM-dd")
$defaultStart = (Get-Date).AddDays(-6).ToString("yyyy-MM-dd")

Write-Host "Please input date range (CST). End date can be any date." -ForegroundColor Cyan
$startDate = Read-CstDate -Prompt "Start date" -DefaultValue $defaultStart
$endDate = Read-CstDate -Prompt "End date" -DefaultValue $defaultEnd

$startObj = [datetime]::ParseExact($startDate, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture)
$endObj = [datetime]::ParseExact($endDate, "yyyy-MM-dd", [System.Globalization.CultureInfo]::InvariantCulture)
if ($startObj -gt $endObj) {
  throw "Invalid range: start date $startDate is after end date $endDate"
}

$args = @(
  "-m", "airesearch",
  "--config", $ConfigPath,
  "--start-date", $startDate,
  "--end-date", $endDate
)

if ($RunOnce) {
  $args += "--run-once"
}
if ($ForceRun) {
  $args += "--force-run"
}

Write-Host "Running: $PythonExe $($args -join ' ')" -ForegroundColor Green
Set-Location $projectRoot
& $PythonExe @args
exit $LASTEXITCODE

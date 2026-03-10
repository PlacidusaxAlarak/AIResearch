param(
    [Parameter(Mandatory = $true)]
    [string]$NewName
)

$current = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$parent = Split-Path -Parent $current
$target = Join-Path $parent $NewName

if (Test-Path $target) {
    throw "Target folder already exists: $target"
}

Set-Location $parent
Rename-Item -LiteralPath $current -NewName $NewName
Write-Output "Renamed to: $target"

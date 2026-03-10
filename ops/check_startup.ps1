$ErrorActionPreference = "Stop"
$startup = [Environment]::GetFolderPath("Startup")
$target = Join-Path $startup "AIResearchAssistant-Daily.cmd"
if (Test-Path $target) {
  Get-Item $target | Select-Object FullName, Length, LastWriteTime
} else {
  Write-Host "NOT_FOUND"
}
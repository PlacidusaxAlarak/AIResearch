$ErrorActionPreference = "Stop"

$startup = [Environment]::GetFolderPath("Startup")
$launcher = Join-Path $startup "AIResearchAssistant-Daily.cmd"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configPath = Join-Path $repoRoot "config.local.yaml"

$lines = @(
  "@echo off",
  "cd /d `"$repoRoot`"",
  "python orchestrator.py --config `"$configPath`" --run-once"
)

Set-Content -Path $launcher -Value $lines -Encoding ASCII
Write-Host "Startup launcher created: $launcher"

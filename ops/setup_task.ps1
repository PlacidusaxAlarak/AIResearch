$ErrorActionPreference = "Stop"

$taskName = "AIResearchAssistant-Daily"
$pythonExe = "python"
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$scriptPath = Join-Path $repoRoot "orchestrator.py"
$configPath = Join-Path $repoRoot "config.local.yaml"

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$scriptPath`" --config `"$configPath`" --run-once" -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Force
Write-Host "Task created/updated: $taskName"

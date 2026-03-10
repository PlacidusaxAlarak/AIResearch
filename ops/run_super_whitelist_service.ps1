param(
    [string]$Config = "config.local.yaml",
    [switch]$ForceRun
)

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$configPath = if ([System.IO.Path]::IsPathRooted($Config)) { $Config } else { Join-Path $repoRoot $Config }

if (!(Test-Path $configPath)) {
    throw "Config not found: $configPath"
}

$args = @("-m", "airesearch", "--config", $configPath, "--run-once")
if ($ForceRun) {
    $args += "--force-run"
}

Push-Location $repoRoot
try {
    & python @args
    if ($LASTEXITCODE -ne 0) {
        throw "airesearch exited with code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}

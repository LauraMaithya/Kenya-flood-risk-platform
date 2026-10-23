param(
    [switch]$DryRun,
    [string]$CountyCode
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path `
    -Parent `
    $PSScriptRoot

$pythonPath = Join-Path `
    $repositoryRoot `
    ".venv\Scripts\python.exe"

$managePath = Join-Path `
    $repositoryRoot `
    "backend\manage.py"

$logDirectory = Join-Path `
    $repositoryRoot `
    "logs"

if (-not (Test-Path $pythonPath)) {
    throw "Virtual-environment Python was not found: $pythonPath"
}

if (-not (Test-Path $managePath)) {
    throw "Django manage.py was not found: $managePath"
}

New-Item `
    -ItemType Directory `
    -Path $logDirectory `
    -Force |
    Out-Null

$logTimestamp = Get-Date -Format "yyyyMMdd-HHmmss"

$logPath = Join-Path `
    $logDirectory `
    "live-refresh-$logTimestamp.log"

$commandArguments = @(
    $managePath
    "live_refresh"
    "--sample-points"
    "3"
    "--timeout"
    "120"
    "--prediction-batch-size"
    "1000"
    "--simulation-seed"
    "scheduled-live-refresh"
)

if ($CountyCode) {
    $commandArguments += @(
        "--county-code"
        $CountyCode
    )
}

if ($DryRun) {
    $commandArguments += "--dry-run"
}

$startedAt = Get-Date

try {
    "Live refresh started at $startedAt" |
        Tee-Object `
            -FilePath $logPath `
            -Append

    & $pythonPath @commandArguments 2>&1 |
        Tee-Object `
            -FilePath $logPath `
            -Append

    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        throw "Live refresh exited with code $exitCode."
    }

    $completedAt = Get-Date

    "Live refresh completed at $completedAt" |
        Tee-Object `
            -FilePath $logPath `
            -Append
}
catch {
    $failedAt = Get-Date

    "Live refresh failed at $failedAt" |
        Tee-Object `
            -FilePath $logPath `
            -Append

    $_ |
        Out-String |
        Tee-Object `
            -FilePath $logPath `
            -Append

    exit 1
}

exit 0
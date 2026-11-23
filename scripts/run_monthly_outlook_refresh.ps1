param(
    [string]$HistoryPath
)

$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$managePath = Join-Path $repositoryRoot "backend\manage.py"
$logDirectory = Join-Path $repositoryRoot "logs"

if (-not $HistoryPath) {
    $HistoryPath = Join-Path `
        $repositoryRoot `
        "data\processed\outlook\real_model_features.csv"
}

foreach ($requiredPath in @($pythonPath, $managePath, $HistoryPath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required file was not found: $requiredPath"
    }
}

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$logTimestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logPath = Join-Path `
    $logDirectory `
    "monthly-outlook-refresh-$logTimestamp.log"

$currentMonthStart = Get-Date -Day 1 -Hour 0 -Minute 0 -Second 0
$completedMonthEnd = $currentMonthStart.AddDays(-1)
$completedMonthStart = Get-Date `
    -Year $completedMonthEnd.Year `
    -Month $completedMonthEnd.Month `
    -Day 1

$startDate = $completedMonthStart.ToString("yyyy-MM-dd")
$endDate = $completedMonthEnd.ToString("yyyy-MM-dd")
$reportPath = Join-Path $logDirectory "monthly-outlook-evaluation.json"
$auditPath = Join-Path $logDirectory "monthly-label-audit.json"

function Invoke-LoggedCommand {
    param([string[]]$Arguments)

    & $pythonPath @Arguments 2>&1 |
        Tee-Object -FilePath $logPath -Append

    if ($LASTEXITCODE -ne 0) {
        throw "Command exited with code ${LASTEXITCODE}: $($Arguments -join ' ')"
    }
}

try {
    "Monthly outlook refresh started at $(Get-Date)" |
        Tee-Object -FilePath $logPath -Append
    "Completed observation month: $startDate through $endDate" |
        Tee-Object -FilePath $logPath -Append

    Invoke-LoggedCommand -Arguments @(
        $managePath
        "refresh_nasa_power"
        "--start-date"
        $startDate
        "--end-date"
        $endDate
        "--sample-points"
        "3"
        "--timeout"
        "120"
        "--prediction-batch-size"
        "1000"
    )

    Invoke-LoggedCommand -Arguments @(
        $managePath
        "refresh_monthly_outlook"
        "--history"
        $HistoryPath
        "--report"
        $reportPath
        "--audit"
        $auditPath
    )

    "Monthly outlook refresh completed at $(Get-Date)" |
        Tee-Object -FilePath $logPath -Append
}
catch {
    "Monthly outlook refresh failed at $(Get-Date)" |
        Tee-Object -FilePath $logPath -Append
    $_ | Out-String | Tee-Object -FilePath $logPath -Append
    exit 1
}

exit 0

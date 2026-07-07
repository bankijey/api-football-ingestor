# Daily bronze ingest — called by Windows Task Scheduler at 2am.
# Logs to scripts/logs/ with a datestamped file.

$projectDir = Split-Path -Parent $PSScriptRoot
$logDir     = Join-Path $PSScriptRoot "logs"
$logFile    = Join-Path $logDir ("ingest-" + (Get-Date -Format "yyyy-MM-dd") + ".log")

if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }

"=== Ingest started at $(Get-Date -Format 'o') ===" | Out-File -Append $logFile

try {
    # Ensure postgres is up before running.
    & docker compose -f "$projectDir\docker-compose.yml" up -d postgres 2>&1 |
        Out-File -Append $logFile

    # Wait for healthy (up to 60s).
    $healthy = $false
    for ($i = 0; $i -lt 20; $i++) {
        $status = & docker inspect --format "{{.State.Health.Status}}" ingestor-postgres 2>&1
        if ($status -eq "healthy") { $healthy = $true; break }
        Start-Sleep -Seconds 3
    }

    if (-not $healthy) {
        "ERROR: postgres did not become healthy in time." | Out-File -Append $logFile
        exit 1
    }

    # Run the ingest (no --leagues = all current leagues; add --leagues 39,140 to restrict).
    # --build rebuilds the image from source before running so this Windows trigger
    # can never drift onto a stale image either (anti-drift, task 0008 — mirrors the
    # compose scheduler cron).
    & docker compose -f "$projectDir\docker-compose.yml" `
        run --build --rm --profile cli ingestor `
        ingest --season 2025 2>&1 |
        Out-File -Append $logFile

    $exit = $LASTEXITCODE
    "=== Ingest finished at $(Get-Date -Format 'o'), exit=$exit ===" | Out-File -Append $logFile
    exit $exit
} catch {
    "FATAL: $_" | Out-File -Append $logFile
    exit 1
}

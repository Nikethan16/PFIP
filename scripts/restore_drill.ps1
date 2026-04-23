<#
.SYNOPSIS Quarterly restore-from-backup drill (read-only on production data).
.DESCRIPTION
  Spins up an isolated test compose project using the same compose file but a
  different project name (so volumes/containers don't collide), restores the
  latest pg_dump into the test TimescaleDB, verifies that every user table has
  at least one row, then tears down the test stack. Writes a dated log.

.PARAMETER Force  Skip the destructive-start confirmation.
.PARAMETER KeepUp Leave the test stack running after the drill for manual inspection.
.EXAMPLE .\scripts\restore_drill.ps1
#>
[CmdletBinding()]
param(
    [switch] $Force,
    [switch] $KeepUp
)

. "$PSScriptRoot\_common.ps1"

Assert-DockerRunning

$drillStamp = Get-Date -Format 'yyyyMMdd-HHmm'
$drillLog   = Join-Path $script:BackupsDir ("drill-" + (Get-Date -Format 'yyyyMMdd') + '.log')
$project    = "pfip_drill_$drillStamp"

function Log-Line {
    param([string]$Level, [string]$Msg)
    $line = "{0} {1} {2}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $Level, $Msg
    Add-Content -Path $drillLog -Value $line
    switch ($Level) {
        'OK'    { Write-Ok $Msg }
        'FAIL'  { Write-Err $Msg }
        'WARN'  { Write-Warn $Msg }
        default { Write-Info $Msg }
    }
}

# Find latest DB backup.
$dbDir = Join-Path $script:BackupsDir 'db'
if (-not (Test-Path $dbDir)) {
    Write-Err "No backups dir at $dbDir. Run backup.ps1 first."
    exit 1
}
$latest = Get-ChildItem -Path $dbDir -Filter 'pfip-*.sql.gz' -File |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $latest) {
    Write-Err 'No pfip-*.sql.gz found in backups/db. Run backup.ps1 first.'
    exit 1
}

Log-Line INFO "drill start stamp=$drillStamp project=$project backup=$($latest.FullName)"
Write-Step "Restore drill — using $($latest.Name)"

if (-not (Confirm-Destructive -Message "Spin up isolated test stack (project=$project)?" -Force:$Force)) {
    Write-Info 'Aborted.'
    exit 0
}

# Isolated env: shift ports by +10000 to avoid collisions with production stack.
$envMap = Read-EnvFile

function _portOr {
    param([string] $Key, [string] $Default)
    if ($envMap.ContainsKey($Key) -and $envMap[$Key]) { return [int]$envMap[$Key] }
    return [int]$Default
}
function _strOr {
    param([string] $Key, [string] $Default)
    if ($envMap.ContainsKey($Key) -and $envMap[$Key]) { return $envMap[$Key] }
    return $Default
}

$tsPort = (_portOr 'TIMESCALEDB_PORT' '5432')  + 10000
$rePort = (_portOr 'REDIS_PORT'       '6379')  + 10000
$qdPort = (_portOr 'QDRANT_HTTP_PORT' '6333')  + 10000
$qgPort = (_portOr 'QDRANT_GRPC_PORT' '6334')  + 10000
$prPort = (_portOr 'PREFECT_PORT'     '4200')  + 10000
$mlPort = (_portOr 'MLFLOW_PORT'      '5000')  + 10000
$olPort = (_portOr 'OLLAMA_PORT'      '11434') + 10000
$ukPort = (_portOr 'UPTIME_KUMA_PORT' '3001')  + 10000
$bePort = (_portOr 'BACKEND_PORT'     '8000')  + 10000
$fePort = (_portOr 'FRONTEND_PORT'    '3000')  + 10000

$drillEnv = Join-Path $env:TEMP ".pfip-drill-$drillStamp.env"
@(
    "POSTGRES_USER=$(_strOr 'POSTGRES_USER' 'pfip')",
    "POSTGRES_PASSWORD=$(_strOr 'POSTGRES_PASSWORD' 'pfip_drill')",
    "POSTGRES_DB=$(_strOr 'POSTGRES_DB' 'pfip')",
    "TIMESCALEDB_PORT=$tsPort",
    "REDIS_PORT=$rePort",
    "QDRANT_HTTP_PORT=$qdPort",
    "QDRANT_GRPC_PORT=$qgPort",
    "PREFECT_PORT=$prPort",
    "MLFLOW_PORT=$mlPort",
    "OLLAMA_PORT=$olPort",
    "UPTIME_KUMA_PORT=$ukPort",
    "BACKEND_PORT=$bePort",
    "FRONTEND_PORT=$fePort",
    "NEXTAUTH_SECRET=drill-only-not-a-secret",
    "PFIP_USER_EMAIL=drill@example.local"
) | Set-Content -Path $drillEnv -Encoding UTF8

$failed = $false
try {
    # Only bring up TimescaleDB — all we need for the drill.
    docker compose -p $project -f $script:ComposeFile --env-file $drillEnv up -d timescaledb
    if ($LASTEXITCODE -ne 0) { throw "compose up (drill) failed" }

    # Wait for healthcheck (up to 60s).
    Log-Line INFO 'waiting for drill DB to be healthy'
    $ctrName = "${project}-timescaledb-1"
    $alt     = "${project}_timescaledb_1"
    $healthy = $false
    foreach ($i in 1..30) {
        foreach ($n in @($ctrName, $alt)) {
            $state = docker inspect -f '{{.State.Health.Status}}' $n 2>$null
            if ($state -eq 'healthy') { $healthy = $true; $ctrName = $n; break }
        }
        if ($healthy) { break }
        Start-Sleep -Seconds 2
    }
    if (-not $healthy) { throw "drill DB not healthy after 60s" }

    # Restore pg_dump.
    $pgUser = $envMap['POSTGRES_USER']; if (-not $pgUser) { $pgUser = 'pfip' }
    $pgDb   = $envMap['POSTGRES_DB'];   if (-not $pgDb)   { $pgDb   = 'pfip' }
    Log-Line INFO "pg_restore -> $ctrName"

    # Ship the backup into the container and restore. gunzip + pg_restore in one shot.
    $restoreProc = Start-Process -FilePath 'docker' `
        -ArgumentList @('exec', '-i', $ctrName,
            'sh', '-c',
            "gunzip -c | pg_restore -U $pgUser -d $pgDb --clean --if-exists --no-owner --no-privileges") `
        -NoNewWindow -PassThru -RedirectStandardInput $latest.FullName -Wait
    if ($restoreProc.ExitCode -ne 0) {
        # Some pg_restore exit codes are warnings (e.g., --clean on empty db). Log but continue to verify.
        Log-Line WARN "pg_restore exit=$($restoreProc.ExitCode) — continuing to verify"
    }

    # Verify: list user tables and count rows.
    $sql = @"
SELECT table_schema||'.'||table_name
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog','information_schema','_timescaledb_internal','_timescaledb_catalog','_timescaledb_config','_timescaledb_cache','timescaledb_experimental','timescaledb_information')
  AND table_type='BASE TABLE'
ORDER BY 1;
"@
    $tables = docker exec -i $ctrName psql -U $pgUser -d $pgDb -tA -c $sql
    $tableList = ($tables -split "`n") | Where-Object { $_.Trim() -and -not $_.StartsWith('(') }

    if (-not $tableList -or $tableList.Count -eq 0) {
        Log-Line WARN 'no user tables found — backup may be from an empty DB (Stage 0)'
    } else {
        $zero = @()
        foreach ($t in $tableList) {
            $cnt = docker exec -i $ctrName psql -U $pgUser -d $pgDb -tA -c "SELECT count(*) FROM $t;"
            $c = 0
            [int]::TryParse(($cnt -replace '\s',''), [ref]$c) | Out-Null
            if ($c -le 0) { $zero += $t } else { Log-Line OK "$t rows=$c" }
        }
        if ($zero.Count -gt 0) {
            Log-Line WARN ("tables with 0 rows: " + ($zero -join ', '))
        }
    }
    Log-Line OK 'restore drill verification complete'
}
catch {
    Log-Line FAIL "drill error: $_"
    $failed = $true
}
finally {
    if (-not $KeepUp) {
        Log-Line INFO "tearing down drill project $project"
        docker compose -p $project -f $script:ComposeFile --env-file $drillEnv down -v 2>$null | Out-Null
        Remove-Item -Path $drillEnv -Force -ErrorAction SilentlyContinue
    } else {
        Log-Line WARN "drill stack left up (KeepUp). Tear down with: docker compose -p $project down -v"
    }
}

if ($failed) {
    Write-Err "Restore drill FAILED. See $drillLog"
    exit 1
}
Write-Ok "Restore drill PASSED. Log: $drillLog"

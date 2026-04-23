<#
.SYNOPSIS Checks every PFIP service's health endpoint. Exits non-zero if any fail.
.PARAMETER Quiet Only print FAIL lines.
.PARAMETER Timeout Per-check HTTP timeout in seconds (default 5).
.EXAMPLE
  .\scripts\health.ps1
  .\scripts\health.ps1 -Timeout 10
#>
[CmdletBinding()]
param(
    [switch] $Quiet,
    [int]    $Timeout = 5
)

. "$PSScriptRoot\_common.ps1"

$env_map = Read-EnvFile
function P($k, $default) {
    if ($env_map.ContainsKey($k) -and $env_map[$k]) { return $env_map[$k] }
    return $default
}

$BE = P 'BACKEND_PORT'     '8000'
$FE = P 'FRONTEND_PORT'    '3000'
$PR = P 'PREFECT_PORT'     '4200'
$ML = P 'MLFLOW_PORT'      '5000'
$QD = P 'QDRANT_HTTP_PORT' '6333'
$UK = P 'UPTIME_KUMA_PORT' '3001'
$OL = P 'OLLAMA_PORT'      '11434'

$PG_USER = P 'POSTGRES_USER' 'pfip'
$PG_DB   = P 'POSTGRES_DB'   'pfip'

$fails = 0
$rows  = @()

function Record {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $script:rows += [pscustomobject]@{
        Name   = $Name
        Status = $(if ($Ok) { 'PASS' } else { 'FAIL' })
        Detail = $Detail
    }
    if (-not $Ok) { $script:fails++ }
}

# TimescaleDB — pg_isready inside the container
try {
    docker exec pfip-timescaledb pg_isready -U $PG_USER -d $PG_DB 1>$null 2>$null
    Record 'TimescaleDB' ($LASTEXITCODE -eq 0) "pg_isready -U $PG_USER -d $PG_DB"
} catch {
    Record 'TimescaleDB' $false "$_"
}

# Redis — PING inside container
try {
    $redisPing = docker exec pfip-redis redis-cli PING 2>$null
    Record 'Redis' ($redisPing -match 'PONG') "redis-cli PING => $redisPing"
} catch {
    Record 'Redis' $false "$_"
}

# Qdrant
Record 'Qdrant'      (Test-HttpOk -Url "http://localhost:$QD/healthz" -TimeoutSec $Timeout) "http://localhost:$QD/healthz"

# Ollama
Record 'Ollama'      (Test-HttpOk -Url "http://localhost:$OL/api/tags"  -TimeoutSec $Timeout) "http://localhost:$OL/api/tags"

# Prefect
Record 'Prefect'     (Test-HttpOk -Url "http://localhost:$PR/api/health" -TimeoutSec $Timeout) "http://localhost:$PR/api/health"

# MLflow — no dedicated /health; root 200 indicates OK.
Record 'MLflow'      (Test-HttpOk -Url "http://localhost:$ML/" -TimeoutSec $Timeout) "http://localhost:$ML/"

# Uptime Kuma — / returns 302 to /dashboard; Test-HttpOk accepts 3xx.
Record 'Uptime Kuma' (Test-HttpOk -Url "http://localhost:$UK/" -TimeoutSec $Timeout) "http://localhost:$UK/"

# Backend — deep health endpoint (may not exist yet at Stage 0 skeleton; fall back to /health).
$beDeep = "http://localhost:$BE/api/v1/health/deep"
$beOk = Test-HttpOk -Url $beDeep -TimeoutSec $Timeout
if (-not $beOk) { $beOk = Test-HttpOk -Url "http://localhost:$BE/health" -TimeoutSec $Timeout }
Record 'Backend'     $beOk $beDeep

# Frontend — /api/health preferred; fall back to /.
$feH = "http://localhost:$FE/api/health"
$feOk = Test-HttpOk -Url $feH -TimeoutSec $Timeout
if (-not $feOk) { $feOk = Test-HttpOk -Url "http://localhost:$FE/" -TimeoutSec $Timeout }
Record 'Frontend'    $feOk $feH

# Render
if (-not $Quiet) {
    Write-Host ''
    foreach ($r in $rows) {
        $color = if ($r.Status -eq 'PASS') { 'Green' } else { 'Red' }
        Write-Host ("  [{0}] {1,-12} {2}" -f $r.Status, $r.Name, $r.Detail) -ForegroundColor $color
    }
    Write-Host ''
}

if ($fails -gt 0) {
    Write-Err "$fails service(s) unhealthy."
    exit 1
}
Write-Ok 'All services healthy.'
exit 0

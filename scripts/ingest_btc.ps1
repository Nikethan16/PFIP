<#
.SYNOPSIS Trigger the BTC daily Prefect flow on-demand.
.DESCRIPTION
  Two trigger modes, tried in order:
    1. Prefect deployment run via `prefect deployment run` inside the backend container
       (expects a deployment named `ingest-btc-daily/prod` — see schedules/prefect_deployments.py).
    2. Direct module invocation: `python -m pfip.ingest.crypto.btc_daily`
       (fallback for early-stage development before Prefect deployments exist).

.PARAMETER DeploymentName Deployment slug; default `ingest-btc-daily/prod`.
.PARAMETER Direct         Skip the deployment path and run the module directly.
.EXAMPLE .\scripts\ingest_btc.ps1
#>
[CmdletBinding()]
param(
    [string] $DeploymentName = 'ingest-btc-daily/prod',
    [switch] $Direct
)

. "$PSScriptRoot\_common.ps1"

Assert-DockerRunning
if (-not (Test-ContainerRunning 'pfip-backend')) {
    Write-Err 'pfip-backend container is not running. Run `.\scripts\up.ps1` first.'
    exit 1
}

if (-not $Direct) {
    Write-Step "Triggering Prefect deployment: $DeploymentName"
    docker exec -i pfip-backend prefect deployment run $DeploymentName
    if ($LASTEXITCODE -eq 0) {
        Write-Ok "Flow run submitted for $DeploymentName"
        exit 0
    }
    Write-Warn 'Prefect deployment trigger failed; falling back to direct module run.'
}

Write-Step 'Running pfip.ingest.crypto.btc_daily directly'
docker exec -i pfip-backend python -m pfip.ingest.crypto.btc_daily
if ($LASTEXITCODE -ne 0) {
    Write-Err "BTC ingest failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}
Write-Ok 'BTC ingest complete.'

<#
.SYNOPSIS
  Bring up the PFIP Docker stack.

.DESCRIPTION
  - Ensures .env exists (copies from .env.example with a warning if missing).
  - Validates Docker Desktop is running.
  - Runs `docker compose up -d` against infra/docker-compose.yml.
  - Prints a URLs summary.

.PARAMETER Service
  Optional: bring up a single service by name (e.g., backend).

.PARAMETER Build
  Pass through `--build` to force rebuild images.

.EXAMPLE
  .\scripts\up.ps1
  .\scripts\up.ps1 -Service backend -Build
#>
[CmdletBinding()]
param(
    [string] $Service,
    [switch] $Build
)

. "$PSScriptRoot\_common.ps1"

Write-Step 'PFIP — starting stack'

Assert-EnvFile
Assert-DockerRunning

$composeArgs = @('up', '-d')
if ($Build)   { $composeArgs += '--build' }
if ($Service) { $composeArgs += $Service }

Invoke-Compose @composeArgs
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose up failed (exit $LASTEXITCODE)"
    exit $LASTEXITCODE
}

$env_map = Read-EnvFile
$beP  = $env_map['BACKEND_PORT']       ; if (-not $beP)  { $beP  = '8000' }
$feP  = $env_map['FRONTEND_PORT']      ; if (-not $feP)  { $feP  = '3000' }
$prP  = $env_map['PREFECT_PORT']       ; if (-not $prP)  { $prP  = '4200' }
$mlP  = $env_map['MLFLOW_PORT']        ; if (-not $mlP)  { $mlP  = '5000' }
$qdP  = $env_map['QDRANT_HTTP_PORT']   ; if (-not $qdP)  { $qdP  = '6333' }
$ukP  = $env_map['UPTIME_KUMA_PORT']   ; if (-not $ukP)  { $ukP  = '3001' }
$olP  = $env_map['OLLAMA_PORT']        ; if (-not $olP)  { $olP  = '11434' }

Write-Host ''
Write-Ok 'Stack is up. Service URLs:'
$rows = @(
    [pscustomobject]@{Service='Frontend    '; URL="http://localhost:$feP"}
    [pscustomobject]@{Service='Backend API '; URL="http://localhost:$beP/docs"}
    [pscustomobject]@{Service='Prefect     '; URL="http://localhost:$prP"}
    [pscustomobject]@{Service='MLflow      '; URL="http://localhost:$mlP"}
    [pscustomobject]@{Service='Qdrant      '; URL="http://localhost:$qdP/dashboard"}
    [pscustomobject]@{Service='Uptime Kuma '; URL="http://localhost:$ukP"}
    [pscustomobject]@{Service='Ollama      '; URL="http://localhost:$olP"}
)
$rows | Format-Table -AutoSize | Out-Host

Write-Info 'Next: run `.\scripts\health.ps1` to verify everything is healthy.'
exit 0

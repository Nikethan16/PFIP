<#
.SYNOPSIS Applies pending Alembic migrations inside the backend container.
.PARAMETER Revision  Target revision (default: head).
.PARAMETER Autogen   Create a new autogen revision instead. Requires -Message.
.PARAMETER Message   Revision message when -Autogen is set.
.EXAMPLE
  .\scripts\migrate.ps1
  .\scripts\migrate.ps1 -Autogen -Message "add trades table"
#>
[CmdletBinding()]
param(
    [string] $Revision = 'head',
    [switch] $Autogen,
    [string] $Message
)

. "$PSScriptRoot\_common.ps1"

Assert-DockerRunning
if (-not (Test-ContainerRunning 'pfip-backend')) {
    Write-Err 'pfip-backend container is not running. Run `.\scripts\up.ps1` first.'
    exit 1
}

if ($Autogen) {
    if (-not $Message) {
        Write-Err '-Message is required when -Autogen is set.'
        exit 2
    }
    Write-Step "alembic revision --autogenerate -m `"$Message`""
    docker exec -i pfip-backend alembic revision --autogenerate -m "$Message"
} else {
    Write-Step "alembic upgrade $Revision"
    docker exec -i pfip-backend alembic upgrade $Revision
}

if ($LASTEXITCODE -ne 0) {
    Write-Err "alembic exited $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Ok 'Migration complete.'

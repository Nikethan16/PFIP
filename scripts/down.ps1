<#
.SYNOPSIS Graceful shutdown of the PFIP stack.
.PARAMETER Volumes  Also remove volumes. DESTRUCTIVE; prompts unless -Force.
.PARAMETER Force    Skip confirmation for destructive flags.
.EXAMPLE
  .\scripts\down.ps1
  .\scripts\down.ps1 -Volumes -Force
#>
[CmdletBinding()]
param(
    [switch] $Volumes,
    [switch] $Force
)

. "$PSScriptRoot\_common.ps1"

Write-Step 'PFIP — shutting down stack'

if (-not (Test-DockerRunning)) {
    Write-Warn 'Docker is not running; nothing to do.'
    exit 0
}

if ($Volumes) {
    if (-not (Confirm-Destructive -Message 'Remove all PFIP data volumes? This DELETES databases + models.' -Force:$Force)) {
        Write-Info 'Aborted.'
        exit 0
    }
    Invoke-Compose down -v
} else {
    Invoke-Compose down
}

Write-Ok 'Stack is down.'

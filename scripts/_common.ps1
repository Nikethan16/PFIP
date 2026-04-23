# _common.ps1 — shared helpers for PFIP PowerShell scripts.
# Dot-source this from every script:  . "$PSScriptRoot\_common.ps1"
# Works on Windows PowerShell 5.1 and PowerShell 7+.

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# -------------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------------
$script:RootDir    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:ScriptsDir = $PSScriptRoot
$script:InfraDir   = Join-Path $script:RootDir 'infra'
$script:EnvFile    = Join-Path $script:RootDir '.env'
$script:EnvExample = Join-Path $script:RootDir '.env.example'
$script:ComposeFile = Join-Path $script:InfraDir 'docker-compose.yml'
$script:BackupsDir = Join-Path $script:RootDir 'backups'

# -------------------------------------------------------------------------
# Colored logging. Works on PS 5.1 (no ANSI support) and PS 7+ (ANSI).
# -------------------------------------------------------------------------
function Write-Info  { param([string]$Msg) Write-Host "[INFO] $Msg" -ForegroundColor Cyan }
function Write-Ok    { param([string]$Msg) Write-Host "[ OK ] $Msg" -ForegroundColor Green }
function Write-Warn  { param([string]$Msg) Write-Host "[WARN] $Msg" -ForegroundColor Yellow }
function Write-Err   { param([string]$Msg) Write-Host "[FAIL] $Msg" -ForegroundColor Red }
function Write-Step  { param([string]$Msg) Write-Host "==> $Msg"    -ForegroundColor Magenta }

# -------------------------------------------------------------------------
# Docker / compose helpers
# -------------------------------------------------------------------------
function Test-DockerRunning {
    try {
        $null = docker info --format '{{.ServerVersion}}' 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Assert-DockerRunning {
    if (-not (Test-DockerRunning)) {
        Write-Err 'Docker daemon is not running. Start Docker Desktop and retry.'
        exit 1
    }
}

function Invoke-Compose {
    [CmdletBinding()]
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Args
    )
    $cargs = @('compose', '-f', $script:ComposeFile, '--env-file', $script:EnvFile) + $Args
    & docker @cargs
}

function Test-ContainerRunning {
    param([Parameter(Mandatory)][string] $Name)
    $state = docker inspect -f '{{.State.Running}}' $Name 2>$null
    return ($LASTEXITCODE -eq 0 -and $state -eq 'true')
}

# -------------------------------------------------------------------------
# .env helpers
# -------------------------------------------------------------------------
function Assert-EnvFile {
    if (-not (Test-Path $script:EnvFile)) {
        Write-Warn ".env not found at $script:EnvFile"
        if (Test-Path $script:EnvExample) {
            Write-Warn 'Copying .env.example -> .env. EDIT SECRETS BEFORE DEPLOYING.'
            Copy-Item $script:EnvExample $script:EnvFile
        } else {
            Write-Err '.env.example also missing. Cannot continue.'
            exit 1
        }
    }
}

function Read-EnvFile {
    <#
    .SYNOPSIS Parse a KEY=VALUE file into a hashtable (ignores comments + blanks).
    #>
    param([string] $Path = $script:EnvFile)

    $result = @{}
    if (-not (Test-Path $Path)) { return $result }

    Get-Content -Path $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith('#')) { return }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { return }
        $k = $line.Substring(0, $eq).Trim()
        $v = $line.Substring($eq + 1).Trim()
        if ($v.StartsWith('"') -and $v.EndsWith('"')) { $v = $v.Substring(1, $v.Length - 2) }
        if ($v.StartsWith("'") -and $v.EndsWith("'")) { $v = $v.Substring(1, $v.Length - 2) }
        $result[$k] = $v
    }
    return $result
}

# -------------------------------------------------------------------------
# HTTP helpers
# -------------------------------------------------------------------------
function Test-HttpOk {
    <#
    .SYNOPSIS Returns $true when URL responds 2xx within $TimeoutSec seconds.
    #>
    param(
        [Parameter(Mandatory)][string] $Url,
        [int] $TimeoutSec = 5,
        [string] $Method = 'GET'
    )
    try {
        $resp = Invoke-WebRequest -Uri $Url -Method $Method -TimeoutSec $TimeoutSec -UseBasicParsing -ErrorAction Stop
        return ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400)
    } catch {
        return $false
    }
}

# -------------------------------------------------------------------------
# Confirm-Destructive — Y/N prompt unless -Force
# -------------------------------------------------------------------------
function Confirm-Destructive {
    param(
        [Parameter(Mandatory)][string] $Message,
        [switch] $Force
    )
    if ($Force) { return $true }
    $resp = Read-Host "$Message [y/N]"
    return ($resp -eq 'y' -or $resp -eq 'Y')
}

# Export nothing explicitly — dot-sourcing makes everything available.

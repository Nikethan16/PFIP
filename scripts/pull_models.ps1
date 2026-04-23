<#
.SYNOPSIS Pulls the Ollama models PFIP depends on (idempotent).
.DESCRIPTION Skips any model already installed. Safe to re-run.
.PARAMETER Models Override the default model list.
.EXAMPLE .\scripts\pull_models.ps1
#>
[CmdletBinding()]
param(
    [string[]] $Models = @()
)

. "$PSScriptRoot\_common.ps1"

Assert-DockerRunning

if (-not (Test-ContainerRunning 'pfip-ollama')) {
    Write-Err 'pfip-ollama container is not running. Run `.\scripts\up.ps1` first.'
    exit 1
}

# Default model list — derive from .env if present, else fall back to plan defaults.
$env_map = Read-EnvFile
if (-not $Models -or $Models.Count -eq 0) {
    $def = $env_map['LLM_DEFAULT_MODEL']; if (-not $def) { $def = 'mistral:7b-instruct' }
    $emb = $env_map['LLM_EMBED_MODEL'];   if (-not $emb) { $emb = 'nomic-embed-text' }
    $Models = @($def, $emb)
}

Write-Step "Pulling Ollama models: $($Models -join ', ')"

# Get installed models (tags) once.
$installed = @()
try {
    $listJson = docker exec pfip-ollama ollama list 2>$null
    # Parse: skip header line, first column is NAME.
    $installed = ($listJson -split "`n") | Select-Object -Skip 1 |
        ForEach-Object { ($_ -split '\s+')[0] } |
        Where-Object { $_ }
} catch {
    Write-Warn "Could not enumerate installed models: $_"
}

$failed = 0
foreach ($m in $Models) {
    if ($installed -contains $m) {
        Write-Ok "already present: $m"
        continue
    }
    Write-Info "pulling $m ..."
    docker exec pfip-ollama ollama pull $m
    if ($LASTEXITCODE -ne 0) {
        Write-Err "pull failed: $m"
        $failed++
    } else {
        Write-Ok "pulled: $m"
    }
}

if ($failed -gt 0) { exit 1 }
Write-Ok 'All models ready.'

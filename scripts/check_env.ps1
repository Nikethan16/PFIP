<#
.SYNOPSIS Validate that .env has the required keys for the current stage.
.DESCRIPTION
  PFIP stages require different sets of keys (Section 12 of the plan). This
  script checks the minimum needed per stage and reports MISSING / EMPTY /
  PLACEHOLDER values. Exits non-zero on any failure.

.PARAMETER Stage  0..7; default 0 (Foundation).
.EXAMPLE .\scripts\check_env.ps1 -Stage 1
#>
[CmdletBinding()]
param(
    [ValidateRange(0,7)]
    [int] $Stage = 0
)

. "$PSScriptRoot\_common.ps1"

# Required-per-stage. Each stage INCLUDES the keys of every previous stage.
$required = @{
    0 = @('POSTGRES_USER','POSTGRES_PASSWORD','POSTGRES_DB','NEXTAUTH_SECRET','PFIP_USER_EMAIL')
    1 = @('LLM_DEFAULT_MODEL','LLM_EMBED_MODEL','HOME_CURRENCY')
    2 = @('FRED_API_KEY','FINNHUB_API_KEY')
    3 = @('NEWSAPI_API_KEY')
    4 = @()
    5 = @('PFIP_USER_PASSWORD_HASH','TAX_YEAR_START','TAX_YEAR_END')
    6 = @('TELEGRAM_BOT_TOKEN','TELEGRAM_BOT_CHAT_ID')
    7 = @()
}

# Known placeholder values treated as missing.
$placeholders = @(
    'change_me_to_random_32_bytes_base64',
    'pfip_dev_change_me',
    'your_',
    'REPLACE_ME'
)

Assert-EnvFile
$envMap = Read-EnvFile

$need = New-Object 'System.Collections.Generic.HashSet[string]'
for ($i = 0; $i -le $Stage; $i++) {
    foreach ($k in $required[$i]) { [void]$need.Add($k) }
}

$missing     = @()
$empty       = @()
$placeholder = @()

foreach ($k in $need) {
    if (-not $envMap.ContainsKey($k)) { $missing += $k; continue }
    $v = $envMap[$k]
    if ([string]::IsNullOrWhiteSpace($v)) { $empty += $k; continue }
    foreach ($p in $placeholders) {
        if ($v -like "*$p*") { $placeholder += $k; break }
    }
}

Write-Step "Environment check for Stage $Stage"
Write-Info ("Required keys: {0}" -f $need.Count)

if ($missing.Count -eq 0 -and $empty.Count -eq 0 -and $placeholder.Count -eq 0) {
    Write-Ok 'All required keys present and non-placeholder.'
    exit 0
}

foreach ($k in $missing)     { Write-Err  "MISSING:     $k" }
foreach ($k in $empty)       { Write-Err  "EMPTY:       $k" }
foreach ($k in $placeholder) { Write-Warn "PLACEHOLDER: $k  (still has default/example value)" }

# Fail on missing/empty; placeholders are a warning for Stage 0 but required to fix by Stage 1+.
$fail = ($missing.Count + $empty.Count)
if ($Stage -ge 1) { $fail += $placeholder.Count }
if ($fail -gt 0) { exit 1 }
exit 0

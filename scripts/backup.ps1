<#
.SYNOPSIS
  PFIP nightly backup: TimescaleDB pg_dump + Qdrant snapshot + MLflow mirror.

.DESCRIPTION
  Writes timestamped artifacts into `<root>/backups/...`:
    - backups/db/pfip-YYYYMMDD-HHMM.sql.gz
    - backups/qdrant/YYYYMMDD/<collection>.snapshot
    - backups/mlflow/YYYYMMDD/ (rsync of mlflow_data volume)
  Optional rclone push if $env:RCLONE_REMOTE is set.
  Retention: 30 daily + 12 monthly (first-of-month) + 5 yearly.
  Appends a log line per run to backups/backup.log.

.PARAMETER Force       Skip any Y/N prompts.
.PARAMETER SkipRclone  Skip the optional rclone remote push even if RCLONE_REMOTE set.
.EXAMPLE .\scripts\backup.ps1
#>
[CmdletBinding()]
param(
    [switch] $Force,
    [switch] $SkipRclone
)

. "$PSScriptRoot\_common.ps1"

Assert-DockerRunning

$stamp     = Get-Date -Format 'yyyyMMdd-HHmm'
$dateTag   = Get-Date -Format 'yyyyMMdd'
$now       = Get-Date
$logFile   = Join-Path $script:BackupsDir 'backup.log'

# Ensure backup dirs exist.
$dbDir     = Join-Path $script:BackupsDir 'db'
$qdDir     = Join-Path $script:BackupsDir 'qdrant'
$mlDir     = Join-Path $script:BackupsDir 'mlflow'
foreach ($d in @($script:BackupsDir, $dbDir, $qdDir, $mlDir)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}

function Log-Line {
    param([string]$Level, [string]$Msg)
    $line = "{0} {1} {2}" -f (Get-Date -Format 'yyyy-MM-ddTHH:mm:ssK'), $Level, $Msg
    Add-Content -Path $logFile -Value $line
}

Log-Line 'INFO' "backup start stamp=$stamp"
Write-Step "PFIP backup — $stamp"

# -------------------------------------------------------------------------
# 1) TimescaleDB pg_dump
# -------------------------------------------------------------------------
$envMap = Read-EnvFile
$pgUser = $envMap['POSTGRES_USER']; if (-not $pgUser) { $pgUser = 'pfip' }
$pgDb   = $envMap['POSTGRES_DB'];   if (-not $pgDb)   { $pgDb   = 'pfip' }

$dbOut = Join-Path $dbDir ("pfip-" + $stamp + '.sql.gz')

if (-not (Test-ContainerRunning 'pfip-timescaledb')) {
    Write-Err 'pfip-timescaledb is not running; cannot pg_dump.'
    Log-Line 'ERROR' 'pg_dump skipped (container not running)'
    exit 1
}

Write-Info "pg_dump -> $dbOut"
# Stream pg_dump through gzip to host file. Using `docker exec -i` so redirection works cross-shell.
# Note: PowerShell redirection is byte-safe on PS 7+, but on 5.1 we must use cmd.exe style.
try {
    $proc = Start-Process -FilePath 'docker' `
        -ArgumentList @('exec', '-i', 'pfip-timescaledb',
            'sh', '-c',
            "pg_dump -U $pgUser -d $pgDb -Fc | gzip -c") `
        -NoNewWindow -PassThru -RedirectStandardOutput $dbOut -Wait
    if ($proc.ExitCode -ne 0) { throw "pg_dump exited $($proc.ExitCode)" }
    $sz = (Get-Item $dbOut).Length
    if ($sz -lt 100) { throw "pg_dump output suspiciously small ($sz bytes)" }
    Write-Ok ("pg_dump ok ({0:N0} bytes)" -f $sz)
    Log-Line 'OK' "pg_dump wrote $dbOut ($sz bytes)"
} catch {
    Write-Err "pg_dump failed: $_"
    Log-Line 'ERROR' "pg_dump failed: $_"
    exit 2
}

# -------------------------------------------------------------------------
# 2) Qdrant snapshots
# -------------------------------------------------------------------------
$qdPort = $envMap['QDRANT_HTTP_PORT']; if (-not $qdPort) { $qdPort = '6333' }
$qdDay  = Join-Path $qdDir $dateTag
if (-not (Test-Path $qdDay)) { New-Item -ItemType Directory -Path $qdDay -Force | Out-Null }

Write-Info "Qdrant snapshots -> $qdDay"
try {
    $colsResp = Invoke-RestMethod -Uri "http://localhost:$qdPort/collections" -TimeoutSec 10
    $colls = @()
    if ($colsResp.result -and $colsResp.result.collections) {
        $colls = $colsResp.result.collections | ForEach-Object { $_.name }
    }
    if (-not $colls -or $colls.Count -eq 0) {
        Write-Warn 'No Qdrant collections yet — skipping snapshot step.'
        Log-Line 'WARN' 'qdrant no collections'
    } else {
        foreach ($c in $colls) {
            $snap = Invoke-RestMethod -Method Post -Uri "http://localhost:$qdPort/collections/$c/snapshots" -TimeoutSec 120
            $snapName = $snap.result.name
            $dst = Join-Path $qdDay ("$c-" + $snapName)
            # Fetch binary snapshot file.
            Invoke-WebRequest -Uri "http://localhost:$qdPort/collections/$c/snapshots/$snapName" -OutFile $dst -UseBasicParsing -TimeoutSec 600
            Write-Ok "qdrant snap: $c => $dst"
            Log-Line 'OK' "qdrant snapshot $c -> $dst"
        }
    }
} catch {
    Write-Warn "Qdrant snapshot step failed: $_"
    Log-Line 'WARN' "qdrant snapshot failed: $_"
}

# -------------------------------------------------------------------------
# 3) MLflow volume mirror via docker-run alpine (rsync installed on demand)
# -------------------------------------------------------------------------
$mlDay = Join-Path $mlDir $dateTag
if (-not (Test-Path $mlDay)) { New-Item -ItemType Directory -Path $mlDay -Force | Out-Null }

Write-Info "MLflow mirror -> $mlDay"
try {
    # Mount the named volume + the host dest into an ephemeral alpine.
    # Use docker volume name as-built by compose: project `pfip` + volume name => pfip_mlflow_data.
    $vol = 'pfip_mlflow_data'
    $mlDayAbs = (Resolve-Path $mlDay).Path
    # Windows docker path quirks: PowerShell passes paths fine with forward slashes.
    $mlDayDocker = ($mlDayAbs -replace '\\', '/')

    docker run --rm `
        -v "${vol}:/src:ro" `
        -v "${mlDayDocker}:/dst" `
        alpine:3.19 `
        sh -c 'apk add --no-cache rsync >/dev/null && rsync -a --delete /src/ /dst/'
    if ($LASTEXITCODE -ne 0) { throw "alpine rsync exited $LASTEXITCODE" }
    Write-Ok 'MLflow mirror ok'
    Log-Line 'OK' "mlflow mirror -> $mlDay"
} catch {
    Write-Warn "MLflow mirror failed: $_"
    Log-Line 'WARN' "mlflow mirror failed: $_"
}

# -------------------------------------------------------------------------
# 4) Optional rclone remote push
# -------------------------------------------------------------------------
$rcloneRemote = $env:RCLONE_REMOTE
if (-not $SkipRclone -and $rcloneRemote) {
    Write-Info "rclone push -> $rcloneRemote"
    try {
        & rclone copy $script:BackupsDir "$rcloneRemote" --transfers 4 --checkers 4 --stats 30s --log-level NOTICE
        if ($LASTEXITCODE -ne 0) { throw "rclone exited $LASTEXITCODE" }
        Write-Ok 'rclone push ok'
        Log-Line 'OK' "rclone push to $rcloneRemote"
    } catch {
        Write-Warn "rclone push failed: $_"
        Log-Line 'WARN' "rclone push failed: $_"
    }
} elseif (-not $rcloneRemote) {
    Write-Info 'RCLONE_REMOTE not set — skipping off-site push.'
}

# -------------------------------------------------------------------------
# 5) Retention: 30 daily + 12 monthly + 5 yearly for DB dumps.
#    Dir-style artifacts (qdrant/mlflow) keep same policy on the date directories.
# -------------------------------------------------------------------------
function Get-RetainedItems {
    <# Given a list of dated items, return the set to KEEP. #>
    param(
        [Parameter(Mandatory)] $Items,      # list of objects with .Date (DateTime) and .Path
        [int] $DailyKeep   = 30,
        [int] $MonthlyKeep = 12,
        [int] $YearlyKeep  = 5
    )
    $keep = New-Object 'System.Collections.Generic.HashSet[string]'
    $sorted = $Items | Sort-Object Date -Descending

    # Daily: keep top N most recent.
    foreach ($i in $sorted | Select-Object -First $DailyKeep) { [void]$keep.Add($i.Path) }

    # Monthly: for each of the last N months, keep the oldest item from the 1st-of-month
    # (or the first item we saw in that month).
    $seenMonths = @{}
    foreach ($i in $sorted) {
        $k = '{0:yyyyMM}' -f $i.Date
        if (-not $seenMonths.ContainsKey($k)) {
            $seenMonths[$k] = $i
            if ($seenMonths.Count -ge $MonthlyKeep) { break }
        }
    }
    foreach ($v in $seenMonths.Values) { [void]$keep.Add($v.Path) }

    # Yearly
    $seenYears = @{}
    foreach ($i in $sorted) {
        $k = '{0:yyyy}' -f $i.Date
        if (-not $seenYears.ContainsKey($k)) {
            $seenYears[$k] = $i
            if ($seenYears.Count -ge $YearlyKeep) { break }
        }
    }
    foreach ($v in $seenYears.Values) { [void]$keep.Add($v.Path) }

    return $keep
}

function Apply-Retention-Files {
    param([string] $Dir, [string] $Pattern)
    if (-not (Test-Path $Dir)) { return }
    $items = Get-ChildItem -Path $Dir -Filter $Pattern -File -ErrorAction SilentlyContinue |
        ForEach-Object {
            # Names look like pfip-YYYYMMDD-HHMM.sql.gz
            if ($_.Name -match 'pfip-(\d{8})-(\d{4})') {
                $d = [DateTime]::ParseExact($matches[1], 'yyyyMMdd', $null)
                [pscustomobject]@{ Date = $d; Path = $_.FullName }
            }
        }
    if (-not $items) { return }
    $keep = Get-RetainedItems -Items $items
    foreach ($i in $items) {
        if (-not $keep.Contains($i.Path)) {
            Write-Info "retention: delete $($i.Path)"
            Remove-Item -Path $i.Path -Force -ErrorAction SilentlyContinue
            Log-Line 'INFO' "retention deleted $($i.Path)"
        }
    }
}

function Apply-Retention-Dirs {
    param([string] $Dir)
    if (-not (Test-Path $Dir)) { return }
    $items = Get-ChildItem -Path $Dir -Directory -ErrorAction SilentlyContinue |
        ForEach-Object {
            if ($_.Name -match '^(\d{8})$') {
                $d = [DateTime]::ParseExact($matches[1], 'yyyyMMdd', $null)
                [pscustomobject]@{ Date = $d; Path = $_.FullName }
            }
        }
    if (-not $items) { return }
    $keep = Get-RetainedItems -Items $items
    foreach ($i in $items) {
        if (-not $keep.Contains($i.Path)) {
            Write-Info "retention: delete dir $($i.Path)"
            Remove-Item -Path $i.Path -Recurse -Force -ErrorAction SilentlyContinue
            Log-Line 'INFO' "retention deleted dir $($i.Path)"
        }
    }
}

Write-Step 'Retention pass'
Apply-Retention-Files -Dir $dbDir -Pattern 'pfip-*.sql.gz'
Apply-Retention-Dirs  -Dir $qdDir
Apply-Retention-Dirs  -Dir $mlDir

Log-Line 'OK' "backup end stamp=$stamp"
Write-Ok "Backup complete — $stamp"

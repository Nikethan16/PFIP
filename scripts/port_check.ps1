<#
.SYNOPSIS Windows — check if any PFIP default ports are already in use.
.DESCRIPTION
  Uses Get-NetTCPConnection when available (Win 8+/Server 2012+); falls back
  to `netstat -ano` for older hosts. Prints the PID + process name of any
  process currently bound to a PFIP default port.
.PARAMETER IncludeDrill  Also check the +10000 shifted drill ports.
.EXAMPLE .\scripts\port_check.ps1
#>
[CmdletBinding()]
param(
    [switch] $IncludeDrill
)

. "$PSScriptRoot\_common.ps1"

$envMap = Read-EnvFile
function P($k, $d) { if ($envMap.ContainsKey($k) -and $envMap[$k]) { return [int]$envMap[$k] } return [int]$d }

$ports = [ordered]@{
    'TimescaleDB' = P 'TIMESCALEDB_PORT' 5432
    'Redis'       = P 'REDIS_PORT'       6379
    'Qdrant HTTP' = P 'QDRANT_HTTP_PORT' 6333
    'Qdrant gRPC' = P 'QDRANT_GRPC_PORT' 6334
    'Prefect'     = P 'PREFECT_PORT'     4200
    'MLflow'      = P 'MLFLOW_PORT'      5000
    'Ollama'      = P 'OLLAMA_PORT'      11434
    'Uptime Kuma' = P 'UPTIME_KUMA_PORT' 3001
    'Backend'     = P 'BACKEND_PORT'     8000
    'Frontend'    = P 'FRONTEND_PORT'    3000
}

if ($IncludeDrill) {
    $drill = [ordered]@{}
    foreach ($k in $ports.Keys) { $drill["$k (drill)"] = $ports[$k] + 10000 }
    foreach ($k in $drill.Keys) { $ports[$k] = $drill[$k] }
}

$haveNet = $null -ne (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)

$conflicts = @()
foreach ($name in $ports.Keys) {
    $port = $ports[$name]
    $inUse = $false
    $proc  = $null; $procPid = $null

    if ($haveNet) {
        $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
                Select-Object -First 1
        if ($conn) {
            $inUse = $true
            $procPid = $conn.OwningProcess
            try {
                $p = Get-Process -Id $procPid -ErrorAction SilentlyContinue
                if ($p) { $proc = $p.ProcessName }
            } catch {}
        }
    } else {
        # netstat fallback
        $out = netstat -ano | Select-String -Pattern (":" + $port + "\s") | Select-Object -First 1
        if ($out) {
            $inUse = $true
            $cols = ($out.ToString() -split '\s+') | Where-Object { $_ }
            if ($cols.Length -ge 1) { $procPid = $cols[-1] }
            try {
                if ($procPid) {
                    $p = Get-Process -Id $procPid -ErrorAction SilentlyContinue
                    if ($p) { $proc = $p.ProcessName }
                }
            } catch {}
        }
    }

    if ($inUse) {
        $conflicts += [pscustomobject]@{
            Port = $port; Name = $name; PID = $procPid; Process = $proc
        }
    }
}

Write-Step 'PFIP port check'
if ($conflicts.Count -eq 0) {
    Write-Ok 'All PFIP default ports are free.'
    exit 0
}
$conflicts | Format-Table -AutoSize | Out-Host
Write-Warn ("$($conflicts.Count) port(s) already bound. Free them or change the port in .env before `up`.")
exit 1

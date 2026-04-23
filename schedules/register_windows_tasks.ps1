<#
.SYNOPSIS Register the two host-level PFIP scheduled tasks on Windows.
.DESCRIPTION
  Creates or updates these Windows Task Scheduler entries:
    - PFIP-Nightly-Backup       : scripts\backup.ps1 daily at 03:15 local
    - PFIP-Quarterly-RestoreDrill : scripts\restore_drill.ps1 on the first
                                     Saturday of Jan/Apr/Jul/Oct at 10:00 local.

  Uses the ScheduledTasks PowerShell module (built into Windows 8+ / Server 2012+).
  Must be run as an Administrator for TaskScheduler write access.

.PARAMETER BackupTime    Time-of-day for nightly backup (default 03:15).
.PARAMETER DrillTime     Time-of-day for quarterly restore drill (default 10:00).
.PARAMETER User          Principal user to run the tasks as (default: current user).
.PARAMETER Unregister    Remove the two tasks instead of installing them.
.PARAMETER Export        Export the two tasks to schedules\windows_task_scheduler.xml.
.EXAMPLE .\schedules\register_windows_tasks.ps1
.EXAMPLE .\schedules\register_windows_tasks.ps1 -Unregister
#>
[CmdletBinding()]
param(
    [string] $BackupTime = '03:15',
    [string] $DrillTime  = '10:00',
    [string] $User       = "$env:USERDOMAIN\$env:USERNAME",
    [switch] $Unregister,
    [switch] $Export
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$TaskModule = Get-Module -ListAvailable -Name 'ScheduledTasks'
if (-not $TaskModule) {
    Write-Error 'ScheduledTasks module not found. This script requires Windows 8+ / Server 2012+.'
    exit 2
}
Import-Module ScheduledTasks -ErrorAction Stop

# Resolve paths.
$repoRoot   = Resolve-Path (Join-Path $PSScriptRoot '..')
$backupPS1  = Join-Path $repoRoot 'scripts\backup.ps1'
$drillPS1   = Join-Path $repoRoot 'scripts\restore_drill.ps1'

if (-not (Test-Path $backupPS1)) { Write-Error "Not found: $backupPS1"; exit 2 }
if (-not (Test-Path $drillPS1))  { Write-Error "Not found: $drillPS1";  exit 2 }

$backupName = 'PFIP-Nightly-Backup'
$drillName  = 'PFIP-Quarterly-RestoreDrill'

# ---------- Unregister path ----------
if ($Unregister) {
    foreach ($n in @($backupName, $drillName)) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            Write-Host "Removed task: $n" -ForegroundColor Yellow
        } else {
            Write-Host "Not installed: $n" -ForegroundColor DarkGray
        }
    }
    exit 0
}

# ---------- Common settings ----------
$psExe = (Get-Command powershell.exe -ErrorAction Stop).Source

$commonSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType S4U -RunLevel Highest

# ---------- 1) Nightly backup: daily at BackupTime ----------
$backupAction  = New-ScheduledTaskAction `
    -Execute $psExe `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$backupPS1`" -Force"

$backupTrigger = New-ScheduledTaskTrigger -Daily -At $BackupTime

$backupTask = New-ScheduledTask `
    -Action $backupAction `
    -Trigger $backupTrigger `
    -Settings $commonSettings `
    -Principal $principal `
    -Description 'PFIP nightly backup — pg_dump + Qdrant snapshots + MLflow mirror + retention.'

if (Get-ScheduledTask -TaskName $backupName -ErrorAction SilentlyContinue) {
    Set-ScheduledTask -TaskName $backupName -Action $backupAction -Trigger $backupTrigger `
        -Settings $commonSettings -Principal $principal | Out-Null
    Write-Host "Updated: $backupName ($BackupTime daily)" -ForegroundColor Green
} else {
    Register-ScheduledTask -TaskName $backupName -InputObject $backupTask | Out-Null
    Write-Host "Registered: $backupName ($BackupTime daily)" -ForegroundColor Green
}

# ---------- 2) Quarterly restore drill: first Saturday of Jan/Apr/Jul/Oct ----------
# Windows Task Scheduler does not natively support "first Saturday of quarter
# months". We register four monthly triggers (one per quarter-month) that fire
# on the first Saturday of that month.

$drillTriggers = @()
foreach ($monthName in @('January','April','July','October')) {
    $t = New-CimInstance -CimClass (Get-CimClass -ClassName MSFT_TaskWeeklyTrigger -Namespace Root/Microsoft/Windows/TaskScheduler) -ClientOnly
    # Monthly-by-DOW via raw COM: use schtasks.exe fallback for portability.
    # Rather than fight the CimClass path, register this via schtasks.exe (see below).
    $drillTriggers += $monthName
}

# Remove any previous version before (re-)registering via schtasks.
if (Get-ScheduledTask -TaskName $drillName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $drillName -Confirm:$false
}

# schtasks.exe supports /SC MONTHLY /MO FIRST /D SAT /M <months>.
# This gives us exactly "first Saturday of Jan,Apr,Jul,Oct".
$schtasksArgs = @(
    '/Create', '/F',
    '/TN', $drillName,
    '/SC', 'MONTHLY',
    '/MO', 'FIRST',
    '/D', 'SAT',
    '/M', 'JAN,APR,JUL,OCT',
    '/ST', $DrillTime,
    '/RL', 'HIGHEST',
    '/TR', "`"$psExe`" -NoProfile -ExecutionPolicy Bypass -File `"$drillPS1`" -Force"
)

Write-Host "Registering: $drillName (first Saturday of Jan/Apr/Jul/Oct @ $DrillTime)" -ForegroundColor Cyan
& schtasks.exe @schtasksArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "schtasks.exe failed with exit $LASTEXITCODE"
    exit $LASTEXITCODE
}
Write-Host "Registered: $drillName" -ForegroundColor Green

# ---------- Optional export ----------
if ($Export) {
    $xmlOut = Join-Path $PSScriptRoot 'windows_task_scheduler.xml'
    $bx = Export-ScheduledTask -TaskName $backupName
    $dx = Export-ScheduledTask -TaskName $drillName

    # Concatenate both exports into a single documentation file. Each Export-ScheduledTask
    # returns an XML <Task> document; we wrap them under <Tasks>.
    $combined = @"
<?xml version="1.0" encoding="UTF-16"?>
<Tasks>
<!-- PFIP scheduled tasks — generated by register_windows_tasks.ps1 -->
$bx
$dx
</Tasks>
"@
    $combined | Out-File -FilePath $xmlOut -Encoding unicode
    Write-Host "Exported tasks -> $xmlOut" -ForegroundColor Green
}

Write-Host ''
Write-Host 'Done. Inspect in Task Scheduler or run:  Get-ScheduledTask PFIP-*' -ForegroundColor Cyan

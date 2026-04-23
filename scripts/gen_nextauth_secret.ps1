<#
.SYNOPSIS Generate a 32-byte base64 NextAuth secret.
.DESCRIPTION
  Prints a cryptographically-random secret to stdout.
  Uses RandomNumberGenerator (cryptographically secure) — NEVER Get-Random (not CSPRNG on PS 5.1).
.EXAMPLE .\scripts\gen_nextauth_secret.ps1
#>
[CmdletBinding()]
param(
    [int] $Bytes = 32,
    [switch] $Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try {
    $buf = New-Object byte[] $Bytes
    $rng.GetBytes($buf)
    $b64 = [Convert]::ToBase64String($buf)
    if ($Quiet) {
        Write-Output $b64
    } else {
        Write-Output ''
        Write-Output "NEXTAUTH_SECRET=$b64"
        Write-Output ''
        [Console]::Error.WriteLine('Paste the line above into your .env file.')
    }
} finally {
    $rng.Dispose()
}

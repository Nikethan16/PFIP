# PFIP - First-run one-shot script
# Run this from: C:\Users\gaura\OneDrive\Desktop\PFIP_app
#
# What it does, in order:
#   1. Verify prerequisites (Docker running, .env exists with secrets)
#   2. docker compose up -d (first time: downloads ~3 GB of images, ~5-10 min)
#   3. Wait for TimescaleDB to be healthy
#   4. Run Alembic migrations (creates all DB tables)
#   5. Pull Ollama LLM models in the background (~4 GB, ~15-30 min depending on connection)
#   6. Health-check all non-LLM services
#   7. Ingest 5 years of BTC daily OHLCV from Coinbase (~30 sec)
#   8. Open the dashboard in your browser
#   9. Print the login credentials
#
# If anything fails, the script stops and prints the error. Nothing is destructive.
# You can re-run this safely - every step is idempotent.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Section($msg) {
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor Cyan
}

function Ok($msg)   { Write-Host "  [OK]   $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [WARN] $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "  [FAIL] $msg" -ForegroundColor Red; exit 1 }

# ---------- 1. Preflight ----------
Section "Step 1/8 - Preflight"

try { docker ps > $null 2>&1; Ok "Docker Desktop is running" }
catch { Fail "Docker Desktop is not running. Start it, then re-run this script." }

if (-not (Test-Path "$Root\.env")) {
    if (Test-Path "$Root\.env.example") {
        Copy-Item "$Root\.env.example" "$Root\.env"
        Warn ".env was missing - copied from .env.example. Check secrets are filled."
    } else {
        Fail ".env missing and .env.example not found."
    }
} else {
    Ok ".env exists"
}

$envContent = Get-Content "$Root\.env" -Raw
if ($envContent -match "NEXTAUTH_SECRET=change_me") { Fail "NEXTAUTH_SECRET still has placeholder. Check .env." }
if ($envContent -match "PFIP_USER_PASSWORD_HASH=\s*\n") { Fail "PFIP_USER_PASSWORD_HASH is empty. Check .env." }
Ok "Auth secrets are set"

# ---------- 2. docker compose up ----------
Section "Step 2/8 - Docker stack up"
Write-Host "  This pulls ~3 GB of images on first run. Progress below:" -ForegroundColor Gray
Write-Host ""

docker compose -f infra\docker-compose.yml --env-file .env up -d
if ($LASTEXITCODE -ne 0) { Fail "docker compose up failed. See errors above." }
Ok "All containers requested to start"

# ---------- 3. Wait for TimescaleDB ----------
Section "Step 3/8 - Waiting for TimescaleDB to be healthy"
$timeout = 120
$elapsed = 0
while ($elapsed -lt $timeout) {
    $status = (docker inspect --format='{{.State.Health.Status}}' pfip-timescaledb 2>$null)
    if ($status -eq "healthy") { Ok "TimescaleDB is healthy"; break }
    Start-Sleep -Seconds 3
    $elapsed += 3
    Write-Host "." -NoNewline -ForegroundColor Gray
}
Write-Host ""
if ($elapsed -ge $timeout) { Fail "TimescaleDB did not become healthy in $timeout seconds. Check: docker logs pfip-timescaledb" }

# ---------- 4. Run migrations ----------
Section "Step 4/8 - Running Alembic migrations"
docker exec pfip-backend alembic upgrade head 2>&1
if ($LASTEXITCODE -ne 0) {
    Warn "Migration failed on first try; waiting 5s for backend to be ready and retrying..."
    Start-Sleep -Seconds 5
    docker exec pfip-backend alembic upgrade head
    if ($LASTEXITCODE -ne 0) { Fail "Migrations failed twice. Check: docker logs pfip-backend" }
}
Ok "Migrations applied"

# ---------- 5. Pull Ollama models (background) ----------
Section "Step 5/8 - Pulling Ollama models in background"
Write-Host "  Mistral 7B (~4 GB) + nomic-embed-text (~300 MB). Total ~4.3 GB." -ForegroundColor Gray
Write-Host "  Running in background - you can continue while it downloads." -ForegroundColor Gray

$ollamaJob = Start-Job -ScriptBlock {
    docker exec pfip-ollama ollama pull mistral:7b-instruct 2>&1
    docker exec pfip-ollama ollama pull nomic-embed-text 2>&1
} -Name "pfip-ollama-pull"
Ok "Ollama pull started as background job (id: $($ollamaJob.Id))"
Write-Host "  To check progress: Receive-Job -Id $($ollamaJob.Id) -Keep" -ForegroundColor Gray

# ---------- 6. Health check non-LLM services ----------
Section "Step 6/8 - Health check (non-LLM services)"

function Probe($name, $url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5 -ErrorAction SilentlyContinue
        if ($r.StatusCode -lt 500) { Ok "$name"; return $true }
    } catch { }
    Warn "$name not responding at $url (may still be starting)"
    return $false
}

Probe "TimescaleDB (via backend)" "http://localhost:8000/api/v1/health"
Probe "Redis (via backend)"       "http://localhost:8000/api/v1/health/deep"
Probe "Qdrant"                    "http://localhost:6333/"
Probe "Prefect"                   "http://localhost:4200/api/health"
Probe "MLflow"                    "http://localhost:5000/"
Probe "Uptime Kuma"               "http://localhost:3001/"
Probe "Frontend"                  "http://localhost:3000/"

# ---------- 7. Ingest first BTC data ----------
Section "Step 7/8 - Ingest 5y of BTC daily OHLCV from Coinbase"
docker exec pfip-backend python -m pfip.prefect.flows.ingest_btc_daily 2>&1
if ($LASTEXITCODE -eq 0) {
    Ok "BTC ingest complete. Dashboard will have real data."
} else {
    Warn "BTC ingest hit an error. You can retry later with: .\scripts\ingest_btc.ps1"
}

# ---------- 8. Open browser + print login ----------
Section "Step 8/8 - Open browser and login"
Start-Process "http://localhost:3000"

Write-Host ""
Write-Host "  Login credentials:" -ForegroundColor Yellow
Write-Host "    Email:    suresh.sahoo@cbcinc.ai" -ForegroundColor White
Write-Host "    Password: pfip-local-2026" -ForegroundColor White
Write-Host ""
Write-Host "  To change password:  see LOGIN.md" -ForegroundColor Gray
Write-Host ""
Write-Host "  Service URLs:" -ForegroundColor Yellow
Write-Host "    Frontend:    http://localhost:3000"
Write-Host "    Backend API: http://localhost:8000/docs"
Write-Host "    Prefect:     http://localhost:4200"
Write-Host "    MLflow:      http://localhost:5000"
Write-Host "    Qdrant:      http://localhost:6333/dashboard"
Write-Host "    Uptime Kuma: http://localhost:3001"
Write-Host ""
Write-Host "  Ollama models still downloading in background (Job $($ollamaJob.Id))." -ForegroundColor Gray
Write-Host "  Chat agent will work once that finishes. Check with:" -ForegroundColor Gray
Write-Host "    Get-Job -Id $($ollamaJob.Id)" -ForegroundColor Gray
Write-Host ""
Section "DONE - PFIP is up"

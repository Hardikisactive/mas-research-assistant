#!/usr/bin/env pwsh
# =============================================================================
# setup.ps1 — First-time project setup script
# Run from e:\PRJ-4\mas_project\
# =============================================================================

$ProjectRoot = $PSScriptRoot | Split-Path -Parent
Set-Location $ProjectRoot

Write-Host "=== Multi-Agent Research Assistant — Setup ===" -ForegroundColor Cyan

# 1. Check Python
$python = "python"
$pyVersion = & $python --version 2>&1
Write-Host "`nPython: $pyVersion" -ForegroundColor Gray

# 2. Install requirements
Write-Host "`n[1/4] Installing Python dependencies..." -ForegroundColor Yellow
& $python -m pip install -r requirements.txt --quiet

# 3. Create .env if not exists
if (-not (Test-Path ".env")) {
    Write-Host "`n[2/4] Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host "  >>> EDIT .env and set your GOOGLE_API_KEY before running!" -ForegroundColor Red
} else {
    Write-Host "`n[2/4] .env already exists." -ForegroundColor Green
}

# 4. Create data directories
Write-Host "`n[3/4] Creating data directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "data/uploads" | Out-Null
New-Item -ItemType Directory -Force -Path "data/vector_store" | Out-Null
New-Item -ItemType Directory -Force -Path "data/sessions" | Out-Null
New-Item -ItemType Directory -Force -Path "evaluation_data/results/charts" | Out-Null
Write-Host "  Directories created." -ForegroundColor Green

# 5. Run tests (no integration)
Write-Host "`n[4/4] Running unit tests to verify installation..." -ForegroundColor Yellow
& $python -m pytest tests/ -m "not integration" -q --tb=short 2>&1 | tail -5

Write-Host "`n=== Setup complete! ===" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Edit .env and set GOOGLE_API_KEY" -ForegroundColor White
Write-Host "  2. Start servers: .\scripts\run_all_servers.ps1" -ForegroundColor White
Write-Host "  3. Start UI:      streamlit run app/ui/app.py" -ForegroundColor White
Write-Host "  4. Run eval:      python -m app.evaluation.harness --patterns BASELINE HIERARCHICAL --limit 10" -ForegroundColor White


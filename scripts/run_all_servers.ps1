#!/usr/bin/env pwsh
# =============================================================================
# run_all_servers.ps1 — Start all required background services
# =============================================================================
# Usage: .\scripts\run_all_servers.ps1
# Press Ctrl+C to stop all servers.
# =============================================================================

$ProjectRoot = $PSScriptRoot | Split-Path -Parent
Set-Location $ProjectRoot

Write-Host "Starting MAS Research Assistant services..." -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray

# Start A2A server (ADK RAG agent endpoint)
Write-Host "`n[1/2] Starting A2A server on port 8002..." -ForegroundColor Yellow
$a2aJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location $root
    & python -m app.protocols.a2a.server 2>&1
} -ArgumentList $ProjectRoot

# Give A2A server time to initialize
Start-Sleep -Seconds 3

# Start MCP server (tools endpoint)
Write-Host "[2/2] Starting MCP server on port 8001..." -ForegroundColor Yellow
$mcpJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location $root
    & python -m app.tools.mcp.server 2>&1
} -ArgumentList $ProjectRoot

Start-Sleep -Seconds 2

Write-Host "`nAll servers started:" -ForegroundColor Green
Write-Host "  A2A Server: http://localhost:8002" -ForegroundColor White
Write-Host "  MCP Server: http://localhost:8001" -ForegroundColor White
Write-Host "`nTo start the Streamlit UI (in a separate terminal):" -ForegroundColor Cyan
Write-Host "  streamlit run app/ui/app.py" -ForegroundColor White
Write-Host "`nPress Ctrl+C to stop all servers...`n" -ForegroundColor Yellow

try {
    while ($true) {
        # Print any new output from jobs
        Receive-Job $a2aJob -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "[A2A] $_" -ForegroundColor Gray }
        Receive-Job $mcpJob -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "[MCP] $_" -ForegroundColor Gray }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host "`nStopping servers..." -ForegroundColor Red
    Stop-Job $a2aJob, $mcpJob -ErrorAction SilentlyContinue
    Remove-Job $a2aJob, $mcpJob -Force -ErrorAction SilentlyContinue
    Write-Host "Done." -ForegroundColor Green
}


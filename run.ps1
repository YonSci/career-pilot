# Start Jobs Find AI locally on Windows (API + dashboard + in-process scheduler).
# Usage:  .\run.ps1            (foreground, Ctrl+C to stop)
#         .\run.ps1 -Port 8010 (different port; update PUBLIC_URL/CORS_ORIGINS in .env to match)
# Output goes to data\logs\server.log (follow it with: Get-Content data\logs\server.log -Wait).
param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1"
)
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
if (-not (Test-Path ".env")) {
    Write-Host "No .env found. Run: python deployment\setup.py" -ForegroundColor Yellow
    exit 1
}
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Host "No virtual environment. Run: python -m venv .venv; .venv\Scripts\pip install -r backend\requirements.lock" -ForegroundColor Yellow
    exit 1
}
if (-not (Test-Path "dashboard\index.html")) {
    Write-Host "No compiled dashboard. Run: corepack pnpm install --frozen-lockfile; corepack pnpm exec vite build --config vite.client.config.ts; then copy dist\dashboard to dashboard" -ForegroundColor Yellow
}
New-Item -ItemType Directory -Force -Path "data\logs" | Out-Null
$env:PYTHONUNBUFFERED = "1"
Write-Host "Jobs Find AI starting on http://$BindHost`:$Port  (log: data\logs\server.log)"
# cmd owns the redirection: PowerShell 5.1 would otherwise turn uvicorn's stderr logging into errors.
& cmd.exe /c "`"$python`" -m uvicorn career.main:app --app-dir backend --host $BindHost --port $Port --log-level info >> data\logs\server.log 2>&1"

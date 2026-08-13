$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$logs = Join-Path $root "runtime-logs"
$localPython = Join-Path $backend ".venv\Scripts\python.exe"
$devVenvPython = "C:\dev\ai-analytics-venv\Scripts\python.exe"
$fallbackPython = Join-Path $env:LOCALAPPDATA "Temp\ai-analytics-agent-venv\Scripts\python.exe"
# Check dev venv first (avoids OneDrive sync corruption of .venv\Scripts)
if (Test-Path $devVenvPython) { $python = $devVenvPython } elseif (Test-Path $localPython) { $python = $localPython } elseif (Test-Path $fallbackPython) { $python = $fallbackPython } else { throw "Python environment not found. Run .\Setup-Agent.ps1 first." }
if (-not (Test-Path (Join-Path $backend ".env"))) { throw "backend\.env is missing. Copy .env.example and add your Neon and Gemini values." }
New-Item -ItemType Directory -Force -Path $logs | Out-Null
function Get-ListenerPid([int]$Port) {
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($connection) { return $connection.OwningProcess }
    return $null
}

# Start-Process can fail on some Windows PowerShell installations when PATH and
# Path are both present in the inherited environment. Normalize the inherited
# variable once before spawning either service.
$pathValue = $env:PATH
Remove-Item Env:Path -ErrorAction SilentlyContinue
$env:PATH = $pathValue

function Start-DetachedProcess([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [string]$Stdout, [string]$Stderr) {
    Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -RedirectStandardOutput $Stdout -RedirectStandardError $Stderr | Out-Null
}
if (-not (Get-ListenerPid 8000)) {
    Start-DetachedProcess $python @("-m", "uvicorn", "app.api.main:app", "--host", "127.0.0.1", "--port", "8000") $backend (Join-Path $logs "backend.log") (Join-Path $logs "backend-error.log")
}
if (-not (Get-ListenerPid 3010)) {
    Start-DetachedProcess "npm.cmd" @("run", "dev", "--", "-p", "3010", "-H", "127.0.0.1") $frontend (Join-Path $logs "frontend.log") (Join-Path $logs "frontend-error.log")
}
$ready = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
    try { $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 2; if ($health.status -eq "ready") { $ready = $true; break } } catch { Start-Sleep -Milliseconds 800 }
}
if (-not $ready) { throw "Backend did not become ready. Check runtime-logs\backend-error.log." }
Write-Host "AI Analytics Agent is ready:" -ForegroundColor Green
Write-Host "http://127.0.0.1:3010"
Write-Host "To stop it later, run .\Stop-Agent.ps1"

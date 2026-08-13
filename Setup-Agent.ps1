$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"
$python = (Get-Command python -ErrorAction Stop).Source
Write-Host "Preparing the AI Analytics Agent..." -ForegroundColor Cyan
& $python -m venv (Join-Path $backend ".venv")
$venvPython = Join-Path $backend ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $backend "requirements.txt")
Push-Location $frontend
try { & npm.cmd install } finally { Pop-Location }
Write-Host "Setup complete. Copy backend\.env.example to backend\.env and add your Neon and Gemini values." -ForegroundColor Green
Write-Host "Then run .\Start-Agent.ps1"

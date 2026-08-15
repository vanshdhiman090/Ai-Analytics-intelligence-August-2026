$ErrorActionPreference = "Stop"
$stopped = @()
foreach ($port in @(3010, 8000)) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($connection in $connections) {
        if ($connection.OwningProcess -and $connection.OwningProcess -notin $stopped) {
            Stop-Process -Id $connection.OwningProcess -Force -ErrorAction SilentlyContinue
            $stopped += $connection.OwningProcess
        }
    }
}
Write-Host "AI Root Cause Investigation Agent stopped." -ForegroundColor Green

$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pidFile = Join-Path $Root ".run\desktop_agent.pid"

if (Test-Path $pidFile) {
    $agentPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($agentPid) {
        Stop-Process -Id $agentPid -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force
}

Push-Location $Root
try {
    docker compose down
} finally {
    Pop-Location
}

Write-Host "UX tracking stack stopped."

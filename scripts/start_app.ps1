$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Venv = Join-Path $Root ".venv"
$RunDir = Join-Path $Root ".run"
$LogDir = Join-Path $Root "logs"
$ExtensionDir = Join-Path $Root "ux-test-platform"
$Python = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }

New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null

$version = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$supportedVersions = @("3.10", "3.11", "3.12")
if ($version -notin $supportedVersions) {
    throw "Python 3.10-3.12 is required for the desktop gaze provider; found $version. Set PYTHON_BIN to a supported Python."
}

if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
    & $Python -m venv $Venv
}
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$VenvPip = Join-Path $Venv "Scripts\pip.exe"

& $VenvPip install -r (Join-Path $Root "requirements.txt")
Push-Location $ExtensionDir
try {
    npm ci
    npm run build
} finally {
    Pop-Location
}

docker info | Out-Null
Push-Location $Root
try {
    docker compose up -d --build postgres rabbitmq api worker
} finally {
    Pop-Location
}

$healthDeadline = (Get-Date).AddMinutes(2)
do {
    try {
        $health = Invoke-RestMethod "http://localhost:8000/health" -TimeoutSec 3
        if ($health.status -eq "ok") { break }
    } catch {
        Start-Sleep -Seconds 2
    }
} while ((Get-Date) -lt $healthDeadline)
if ((Get-Date) -ge $healthDeadline) {
    throw "Backend did not become healthy at http://localhost:8000/health"
}

$pidFile = Join-Path $RunDir "desktop_agent.pid"
if (Test-Path $pidFile) {
    $oldPid = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "Desktop agent already running with PID $oldPid"
        exit 0
    }
}

$stdout = Join-Path $LogDir "desktop_agent.log"
$stderr = Join-Path $LogDir "desktop_agent.error.log"
$process = Start-Process -FilePath $VenvPython `
    -ArgumentList (Join-Path $Root "desktop_agent.py") `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru
Set-Content -LiteralPath $pidFile -Value $process.Id

Write-Host "Started. Load unpacked extension from: $(Join-Path $ExtensionDir 'dist')"
Write-Host "Desktop agent PID: $($process.Id)"

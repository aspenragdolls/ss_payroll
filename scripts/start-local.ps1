# Starts SS Payroll locally: venv, deps, migrations, uvicorn, browser.
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Write-Status([string]$Message) {
    Write-Host "[SS Payroll] $Message"
}

function Wait-ForExit([string]$Prompt = "Press Enter to close this window.") {
    Read-Host $Prompt | Out-Null
}

if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
    Write-Host "Missing .env file. Copy .env.example to .env and set your variables." -ForegroundColor Red
    Wait-ForExit
    exit 1
}

$venvDir = Join-Path $ProjectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvPip = Join-Path $venvDir "Scripts\pip.exe"

if (-not (Test-Path $venvPython)) {
    $systemPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $systemPython) {
        Write-Host "Python was not found on PATH. Install Python 3.11+ and try again." -ForegroundColor Red
        Wait-ForExit
        exit 1
    }

    Write-Status "Creating virtual environment..."
    & $systemPython.Source -m venv $venvDir
}

Write-Status "Installing dependencies..."
& $venvPip install -q -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to install dependencies." -ForegroundColor Red
    Wait-ForExit
    exit 1
}

Write-Status "Running database migrations..."
& $venvPython -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host "Migration failed. Check DATABASE_URL in .env." -ForegroundColor Red
    Wait-ForExit
    exit 1
}

function Test-PortAvailable([int]$Port) {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
    try {
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener.Server.IsBound) {
            $listener.Stop()
        }
    }
}

function Get-AvailablePort([int]$PreferredPort) {
    if (Test-PortAvailable $PreferredPort) {
        return $PreferredPort
    }

    Write-Host "Port $PreferredPort is already in use." -ForegroundColor Yellow
    for ($candidate = $PreferredPort + 1; $candidate -le ($PreferredPort + 20); $candidate++) {
        if (Test-PortAvailable $candidate) {
            Write-Status "Using alternate port $candidate instead."
            return $candidate
        }
    }

    throw "No open port found between $PreferredPort and $($PreferredPort + 20)."
}

$preferredPort = 8000
$parsedPort = 0
if ($env:PORT -and [int]::TryParse($env:PORT, [ref]$parsedPort)) {
    $preferredPort = $parsedPort
}

$port = Get-AvailablePort $preferredPort
$url = "http://127.0.0.1:$port"

Write-Status "Starting server at $url"
Write-Status "Leave this window open while using the app. Press Ctrl+C to stop."

$browserJob = Start-Job -ScriptBlock {
    param($TargetUrl, $TargetPort, $TimeoutSeconds)
    for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
        try {
            $client = New-Object System.Net.Sockets.TcpClient
            $client.Connect("127.0.0.1", $TargetPort)
            $client.Close()
            Start-Process $TargetUrl
            return
        } catch {
            Start-Sleep -Seconds 1
        }
    }
} -ArgumentList $url, $port, 45

try {
    & $venvPython -m uvicorn app.main:app --host 127.0.0.1 --port $port --reload
} finally {
    if ($browserJob.State -eq "Running") {
        Stop-Job $browserJob | Out-Null
    }
    Remove-Job $browserJob -Force | Out-Null
}

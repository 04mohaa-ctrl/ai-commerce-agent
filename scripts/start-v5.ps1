param(
    [int]$Port = 8510,
    [string]$PythonExecutable = '',
    [string]$DatabasePath = 'data/v5-local.db',
    [switch]$LiveProviders
)

$projectDirectory = Split-Path -Parent $PSScriptRoot
if (-not $PythonExecutable) {
    $PythonExecutable = Join-Path $projectDirectory '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $PythonExecutable)) {
    throw 'Supply -PythonExecutable pointing to Python with requirements-lock.txt installed.'
}
if ($Port -lt 1024 -or $Port -gt 65535) { throw 'Choose a port from 1024 to 65535.' }
$probe = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
try { $probe.Start() } finally { $probe.Stop() }
$previousDatabase = $env:DATABASE_PATH
$previousOffline = $env:COMMERCE_OFFLINE
Push-Location -LiteralPath $projectDirectory
try {
    $env:DATABASE_PATH = $DatabasePath
    $env:COMMERCE_OFFLINE = if ($LiveProviders) { '0' } else { '1' }
    Write-Host "V5 local workspace: http://127.0.0.1:$Port"
    & $PythonExecutable -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port
} finally {
    $env:DATABASE_PATH = $previousDatabase
    $env:COMMERCE_OFFLINE = $previousOffline
    Pop-Location
}

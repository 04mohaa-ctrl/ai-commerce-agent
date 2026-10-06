param([int]$Port = 8501)

$projectDirectory = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    Write-Error 'Create .venv and install requirements.txt first. See README.md.'
    exit 1
}
Push-Location -LiteralPath $projectDirectory
try {
    & $pythonExecutable -m streamlit run app.py --server.address 127.0.0.1 --server.port $Port
} finally {
    Pop-Location
}

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$PythonPath = Join-Path $ProjectDir ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $PythonPath)) {
    Write-Host "Chưa có .venv. Chạy các lệnh sau:" -ForegroundColor Yellow
    Write-Host "  py -3.12 -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
    exit 1
}

Set-Location -LiteralPath $ProjectDir
& $PythonPath "main.py"


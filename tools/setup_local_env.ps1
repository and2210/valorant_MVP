$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$appRoot = Join-Path $env:LOCALAPPDATA "RadianteDaily"
$venvRoot = Join-Path $appRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    py -3 -m venv $venvRoot
}

& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $projectRoot "requirements.txt")

Write-Host "Radiante Daily environment ready at $venvRoot"

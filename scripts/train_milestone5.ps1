$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "No local environment found. Run scripts\bootstrap.ps1 first."
}

Push-Location $ProjectRoot
try {
    & $Python -m qld_road_safety.cli train-milestone5 --project-root .
    if ($LASTEXITCODE -ne 0) {
        throw "Milestone 5 training failed with exit code $LASTEXITCODE."
    }
}
finally {
    Pop-Location
}

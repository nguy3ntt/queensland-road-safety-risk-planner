$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Invoke-PythonCommand {
    param([string[]]$CommandArguments)

    & $Python @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: $($CommandArguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "No local environment found. Run scripts\bootstrap.ps1 first."
}

Push-Location $ProjectRoot
try {
    Invoke-PythonCommand @("-m", "qld_road_safety.cli", "validate-config", "--config", "configs/base.yaml")
    Invoke-PythonCommand @("-m", "qld_road_safety.cli", "validate-manifest", "--manifest", "configs/provenance.example.yaml")
    Invoke-PythonCommand @("-m", "pytest")
    Invoke-PythonCommand @("-m", "ruff", "check", "src", "tests")
    Invoke-PythonCommand @("-m", "ruff", "format", "--check", "src", "tests")
    Invoke-PythonCommand @("-m", "mypy")
}
finally {
    Pop-Location
}

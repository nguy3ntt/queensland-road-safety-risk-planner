[CmdletBinding()]
param(
    [string]$BasePython = "python"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VirtualEnvironment = Join-Path $ProjectRoot ".venv"
$Python = Join-Path $VirtualEnvironment "Scripts\python.exe"

function Invoke-PythonCommand {
    param([string[]]$CommandArguments)

    & $Python @CommandArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code ${LASTEXITCODE}: $($CommandArguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    & $BasePython -m venv $VirtualEnvironment
}

Push-Location $ProjectRoot
try {
    Invoke-PythonCommand @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-PythonCommand @("-m", "pip", "install", "-e", ".[dev,geo,ml,app]")
    Invoke-PythonCommand @("-m", "qld_road_safety.cli", "validate-config", "--config", "configs/base.yaml")
    Invoke-PythonCommand @("-m", "qld_road_safety.cli", "validate-manifest", "--manifest", "configs/provenance.example.yaml")
    Invoke-PythonCommand @("-m", "pytest")
    Invoke-PythonCommand @("-m", "ruff", "check", "src", "tests", "scripts")
    Invoke-PythonCommand @("-m", "ruff", "format", "--check", "src", "tests", "scripts")
    Invoke-PythonCommand @("-m", "mypy")
}
finally {
    Pop-Location
}

Write-Host "Project environment is ready." -ForegroundColor Green

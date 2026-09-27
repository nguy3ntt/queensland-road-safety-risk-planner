param([string]$ProjectRoot = ".", [int]$Port = 8000)
$ErrorActionPreference = "Stop"
$python = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Run scripts/bootstrap.ps1 first." }
& $python -m qld_road_safety.cli serve-milestone6 --project-root $ProjectRoot --port $Port
exit $LASTEXITCODE

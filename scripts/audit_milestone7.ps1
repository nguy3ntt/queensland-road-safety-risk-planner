param([string]$ProjectRoot = ".")
$ErrorActionPreference = "Stop"
$python = Join-Path $ProjectRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $python)) { throw "Run scripts/bootstrap.ps1 first." }
& $python -m qld_road_safety.cli audit-milestone7 --project-root $ProjectRoot
exit $LASTEXITCODE

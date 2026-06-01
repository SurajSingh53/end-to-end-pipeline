$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Output "Running API regression tests..."
python -m unittest discover -s tests -p "test_*.py" -v

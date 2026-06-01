$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

if (Test-CommandExists "docker") {
    Write-Output "Using runtime: docker compose"
    & docker compose -f docker-compose.yml down
} elseif (Test-CommandExists "podman-compose") {
    Write-Output "Using runtime: podman-compose"
    & podman-compose -f docker-compose.yml down
} elseif (Test-CommandExists "docker-compose") {
    Write-Output "Using runtime: docker-compose"
    & "docker-compose" -f docker-compose.yml down
} else {
    throw "No supported compose runtime found. Install Docker (docker compose) or Podman (podman-compose)."
}

param(
    [switch]$Build,
    [switch]$Detach
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Invoke-ComposeUp {
    param(
        [string]$Runtime,
        [switch]$DoBuild,
        [switch]$DoDetach
    )

    if ($Runtime -eq "docker compose") {
        if ($DoBuild -and $DoDetach) {
            & docker compose -f docker-compose.yml up --build -d
        } elseif ($DoBuild) {
            & docker compose -f docker-compose.yml up --build
        } elseif ($DoDetach) {
            & docker compose -f docker-compose.yml up -d
        } else {
            & docker compose -f docker-compose.yml up
        }
    } elseif ($Runtime -eq "docker-compose") {
        if ($DoBuild -and $DoDetach) {
            & "docker-compose" -f docker-compose.yml up --build -d
        } elseif ($DoBuild) {
            & "docker-compose" -f docker-compose.yml up --build
        } elseif ($DoDetach) {
            & "docker-compose" -f docker-compose.yml up -d
        } else {
            & "docker-compose" -f docker-compose.yml up
        }
    } else {
        if ($DoBuild -and $DoDetach) {
            & podman-compose -f docker-compose.yml up --build -d
        } elseif ($DoBuild) {
            & podman-compose -f docker-compose.yml up --build
        } elseif ($DoDetach) {
            & podman-compose -f docker-compose.yml up -d
        } else {
            & podman-compose -f docker-compose.yml up
        }
    }
}

$composeCmd = $null

if (Test-CommandExists "docker") {
    $composeCmd = "docker compose"
} elseif (Test-CommandExists "podman-compose") {
    if (Test-CommandExists "podman") {
        try {
            & podman machine start podman-machine-default | Out-Null
        } catch {
            # Machine may already be running; ignore startup error.
        }
    }
    $composeCmd = "podman-compose"
} elseif (Test-CommandExists "docker-compose") {
    $composeCmd = "docker-compose"
} else {
    throw "No supported compose runtime found. Install Docker (docker compose) or Podman (podman-compose)."
}

Write-Output ("Using runtime: " + $composeCmd)
Invoke-ComposeUp -Runtime $composeCmd -DoBuild:$Build -DoDetach:$Detach

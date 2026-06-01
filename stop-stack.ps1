$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Output "[1/4] Checking health endpoint..."
$health = $null
for ($i = 1; $i -le 30; $i++) {
    try {
        $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -Method Get
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}

if ($null -eq $health) {
    throw "Health check failed after waiting for startup"
}

if ($health.status -ne "ok") {
    throw "Health check failed"
}

Write-Output "[2/4] Checking metrics endpoint..."
$metrics = Invoke-RestMethod -Uri "http://localhost:8000/metrics" -Method Get
if ($null -eq $metrics.entries -or $null -eq $metrics.conversion_rate) {
    throw "Metrics response missing required fields"
}

Write-Output "[3/4] Checking funnel endpoint..."
$funnel = Invoke-RestMethod -Uri "http://localhost:8000/funnel" -Method Get
if ($null -eq $funnel.is_monotonic_non_increasing) {
    throw "Funnel response missing monotonic field"
}

Write-Output "[4/4] Checking artifacts..."
$required = @(
    "artifacts/events.jsonl",
    "artifacts/sessions.json",
    "artifacts/metrics.json"
)
foreach ($path in $required) {
    if (-not (Test-Path $path)) {
        throw "Missing artifact: $path"
    }
}

Write-Output "PASS"
Write-Output ("entries=" + $metrics.entries)
Write-Output ("purchasers=" + $metrics.purchasers)
Write-Output ("conversion_rate=" + $metrics.conversion_rate)
Write-Output ("vision_mode=" + $metrics.vision_processing_mode)
Write-Output ("cameras_processed=" + $metrics.cameras_processed)
Write-Output ("funnel_monotonic=" + $funnel.is_monotonic_non_increasing)

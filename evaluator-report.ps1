$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Test-CommandExists {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-ComposeRuntime {
    if (Test-CommandExists "docker") {
        return "docker compose"
    }
    if (Test-CommandExists "podman-compose") {
        return "podman-compose"
    }
    if (Test-CommandExists "docker-compose") {
        return "docker-compose"
    }
    return $null
}

function Test-ServiceContainerRunning {
    param([string]$Runtime)

    if ([string]::IsNullOrWhiteSpace($Runtime)) {
        return $false
    }

    if ($Runtime -eq "docker compose") {
        try {
            $names = & docker compose -f docker-compose.yml ps --services --status running
            return @($names) -contains "store-intelligence"
        } catch {
            return $false
        }
    }

    if ($Runtime -eq "podman-compose") {
        try {
            $names = & podman ps --format "{{.Names}}"
            return @($names) -contains "store-intelligence"
        } catch {
            return $false
        }
    }

    if ($Runtime -eq "docker-compose") {
        try {
            $names = & "docker-compose" -f docker-compose.yml ps --services --filter status=running
            return @($names) -contains "store-intelligence"
        } catch {
            return $false
        }
    }

    return $false
}

function Test-EndpointWithRetry {
    param(
        [string]$Uri,
        [int]$MaxAttempts = 30,
        [int]$DelaySeconds = 2
    )

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        try {
            return Invoke-RestMethod -Uri $Uri -Method Get
        } catch {
            if ($i -eq $MaxAttempts) {
                throw "Endpoint unavailable after retries: $Uri"
            }
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

$results = @()
function Add-Result {
    param(
        [string]$Check,
        [bool]$Passed,
        [string]$Details
    )

    $results += [PSCustomObject]@{
        Check = $Check
        Passed = $Passed
        Details = $Details
    }
}

try {
    Write-Output "Running Acceptance Gate Checks..."

    $runtime = Get-ComposeRuntime
    $containerRunning = Test-ServiceContainerRunning -Runtime $runtime
    $runtimeLabel = if ([string]::IsNullOrWhiteSpace($runtime)) { "none" } else { $runtime }
    Add-Result -Check "System Execution" -Passed $containerRunning -Details ($(if ($containerRunning) { "store-intelligence service is running via " + $runtimeLabel } else { "store-intelligence service is not running (detected runtime: " + $runtimeLabel + ")" }))

    $health = Test-EndpointWithRetry -Uri "http://localhost:8000/health"
    $metrics = Test-EndpointWithRetry -Uri "http://localhost:8000/metrics"
    $funnel = Test-EndpointWithRetry -Uri "http://localhost:8000/funnel"
    $sample = Test-EndpointWithRetry -Uri "http://localhost:8000/events/sample?limit=20"

    $metricsOk = ($null -ne $metrics.entries) -and ($null -ne $metrics.conversion_rate) -and ($null -ne $metrics.vision_processing_mode)
    Add-Result -Check "API Availability" -Passed $metricsOk -Details ($(if ($metricsOk) { "/metrics returned expected fields" } else { "/metrics missing expected fields" }))

    $requiredEventFields = @("event_id","event_type","event_time","store_id","session_id","confidence","dedupe_key","reason_code","source")
    $events = @($sample.events)
    $hasEvents = $events.Count -gt 0
    $schemaOk = $true
    if ($hasEvents) {
        foreach ($field in $requiredEventFields) {
            if (-not ($events[0].PSObject.Properties.Name -contains $field)) {
                $schemaOk = $false
                break
            }
        }
    } else {
        $schemaOk = $false
    }
    Add-Result -Check "Event Generation" -Passed ($hasEvents -and $schemaOk) -Details ($(if ($hasEvents -and $schemaOk) { "Structured events are present and schema-complete" } else { "Events missing or schema incomplete" }))

    $designPath = "docs/DESIGN.md"
    $choicesPath = "docs/CHOICES.md"
    $designOk = (Test-Path $designPath) -and ((Get-Content $designPath | Measure-Object -Line).Lines -ge 20)
    $choicesOk = (Test-Path $choicesPath) -and ((Get-Content $choicesPath | Measure-Object -Line).Lines -ge 20)
    Add-Result -Check "Documentation" -Passed ($designOk -and $choicesOk) -Details ($(if ($designOk -and $choicesOk) { "DESIGN.md and CHOICES.md are present and non-trivial" } else { "Documentation missing or too short" }))

    $metrics2 = Test-EndpointWithRetry -Uri "http://localhost:8000/metrics"
    $funnel2 = Test-EndpointWithRetry -Uri "http://localhost:8000/funnel"
    $stabilityOk = ($metrics2.entries -ge 0) -and ($null -ne $funnel2.is_monotonic_non_increasing)
    Add-Result -Check "Stability" -Passed $stabilityOk -Details ($(if ($stabilityOk) { "Repeated API calls succeeded" } else { "Repeated API calls failed" }))

    $purchasersWithinEntries = ($metrics2.purchasers -le $metrics2.entries)
    $funnelMonotonic = [bool]$funnel2.is_monotonic_non_increasing
    $businessLogicOk = $purchasersWithinEntries -and $funnelMonotonic
    Add-Result -Check "Business Logic Consistency" -Passed $businessLogicOk -Details (
        $(if ($businessLogicOk) {
            "purchasers<=entries and funnel monotonic checks passed"
        } else {
            "consistency invariant failed (purchasers<=entries or funnel monotonic)"
        })
    )

    Write-Output ""
    Write-Output "Acceptance Gate Report"
    Write-Output "======================"
    foreach ($r in $results) {
        $status = if ($r.Passed) { "PASS" } else { "FAIL" }
        Write-Output ("[{0}] {1} - {2}" -f $status, $r.Check, $r.Details)
    }

    $overallPass = -not ($results | Where-Object { -not $_.Passed })
    Write-Output ""
    if ($overallPass) {
        Write-Output "OVERALL: PASS"
        exit 0
    }

    Write-Output "OVERALL: FAIL"
    exit 1
}
catch {
    Write-Output ""
    Write-Output "Acceptance Gate Report"
    Write-Output "======================"
    Write-Output "[FAIL] Execution Error - $($_.Exception.Message)"
    Write-Output "OVERALL: FAIL"
    exit 1
}

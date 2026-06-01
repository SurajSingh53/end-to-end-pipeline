$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

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

function Test-ArtifactExists {
    param([string]$Path)
    return Test-Path $Path
}

$start = Get-Date
$script:report = @()

function Add-Score {
    param(
        [string]$Area,
        [int]$Score,
        [int]$Max,
        [string]$Note
    )

    $script:report += [PSCustomObject]@{
        Area = $Area
        Score = $Score
        Max = $Max
        Note = $Note
    }
}

try {
    $health = Test-EndpointWithRetry -Uri "http://localhost:8000/health"
    $metrics = Test-EndpointWithRetry -Uri "http://localhost:8000/metrics"
    $funnel = Test-EndpointWithRetry -Uri "http://localhost:8000/funnel"
    $sample = Test-EndpointWithRetry -Uri "http://localhost:8000/events/sample?limit=20"

    $execScore = if ($health.status -eq "ok") { 20 } else { 0 }
    Add-Score -Area "System execution" -Score $execScore -Max 20 -Note "Health endpoint reachable"

    $eventFields = @("event_id","event_type","event_time","store_id","session_id","confidence","dedupe_key","reason_code","source")
    $events = @($sample.events)
    $hasEvents = $events.Count -gt 0
    $schemaOk = $false
    if ($hasEvents) {
        $presentCount = 0
        foreach ($field in $eventFields) {
            if ($events[0].PSObject.Properties.Name -contains $field) {
                $presentCount += 1
            }
        }
        $schemaOk = ($presentCount -eq $eventFields.Count)
    }

    $detectionScore = 0
    if ($hasEvents) {
        $detectionScore += 10
    }
    if ($schemaOk) {
        $detectionScore += 10
    }
    Add-Score -Area "Detection and event quality" -Score $detectionScore -Max 20 -Note "Event presence and schema completeness"

    $apiScore = 0
    if (($null -ne $metrics.entries) -and ($null -ne $metrics.conversion_rate)) {
        $apiScore += 10
    }
    if ($null -ne $funnel.is_monotonic_non_increasing) {
        $apiScore += 10
    }
    Add-Score -Area "API and business logic" -Score $apiScore -Max 20 -Note "Metrics/funnel completeness and invariant surface"

    $artifactScore = 0
    if (Test-ArtifactExists -Path "artifacts/events.jsonl") { $artifactScore += 5 }
    if (Test-ArtifactExists -Path "artifacts/sessions.json") { $artifactScore += 5 }
    if (Test-ArtifactExists -Path "artifacts/metrics.json") { $artifactScore += 5 }
    Add-Score -Area "Persistence and traceability" -Score $artifactScore -Max 15 -Note "Expected artifacts generated"

    $docsScore = 0
    if (Test-Path "docs/DESIGN.md") { $docsScore += 5 }
    if (Test-Path "docs/CHOICES.md") { $docsScore += 5 }
    if (Test-Path "docs/FUTURE_ENHANCEMENTS.md") { $docsScore += 5 }
    if (Test-Path "docs/EVALUATOR_GUIDE.md") { $docsScore += 5 }
    if (Test-Path "docs/RUBRIC_MAPPING.md") { $docsScore += 5 }
    Add-Score -Area "Documentation quality" -Score $docsScore -Max 25 -Note "Design, trade-offs, roadmap, evaluator docs"

    $total = ($script:report | Measure-Object -Property Score -Sum).Sum
    $maxTotal = ($script:report | Measure-Object -Property Max -Sum).Sum

    $elapsed = (Get-Date) - $start

    Write-Output "Evaluator Readiness Report"
    Write-Output "=========================="
    foreach ($row in $script:report) {
        Write-Output (("[{0}/{1}] {2} - {3}") -f $row.Score, $row.Max, $row.Area, $row.Note)
    }

    Write-Output ""
    Write-Output (("TOTAL: {0}/{1}") -f $total, $maxTotal)
    Write-Output (("RUNTIME_SECONDS: {0}") -f [math]::Round($elapsed.TotalSeconds, 2))

    if ($total -ge 80) {
        Write-Output "READINESS: STRONG"
        exit 0
    }
    if ($total -ge 65) {
        Write-Output "READINESS: MODERATE"
        exit 0
    }

    Write-Output "READINESS: WEAK"
    exit 1
}
catch {
    Write-Output "Evaluator Readiness Report"
    Write-Output "=========================="
    Write-Output ("[ERROR] " + $_.Exception.Message)
    Write-Output "READINESS: WEAK"
    exit 1
}

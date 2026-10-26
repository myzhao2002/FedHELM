$ErrorActionPreference = 'Stop'
try {
    $fedhelmRecord = Join-Path $PSScriptRoot 'runtime\cluster\launcher.json'
    if (-not (Test-Path -LiteralPath $fedhelmRecord)) { throw 'Launcher record is missing. Use Ctrl+C in the original launcher window.' }
    $fedhelmInfo = Get-Content -LiteralPath $fedhelmRecord -Raw | ConvertFrom-Json
    if ($fedhelmInfo.workspace -ne $PSScriptRoot) { throw 'Workspace mismatch; no process stopped.' }
    $fedhelmProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($fedhelmInfo.pid)"
    if (-not $fedhelmProcess) { Write-Host 'Platform is already stopped.'; exit 0 }
    $fedhelmBirth = ([DateTimeOffset]$fedhelmProcess.CreationDate).ToUnixTimeSeconds()
    if ([Math]::Abs($fedhelmBirth - $fedhelmInfo.recorded_at) -gt 30 -or $fedhelmProcess.CommandLine -notmatch '-m scripts.cluster') {
        throw 'Process identity mismatch; no process stopped.'
    }
    # Business children may exit themselves while taskkill walks the tree.
    # Keep birth times so a reused PID cannot be mistaken for a surviving child.
    $fedhelmSnapshot = @(Get-CimInstance Win32_Process -Property ProcessId,ParentProcessId,CreationDate)
    $fedhelmOwned = @($fedhelmProcess)
    $fedhelmFrontier = @($fedhelmProcess.ProcessId)
    while ($fedhelmFrontier.Count -gt 0) {
        $fedhelmNext = @($fedhelmSnapshot | Where-Object { $_.ParentProcessId -in $fedhelmFrontier -and $_.ProcessId -notin $fedhelmOwned.ProcessId })
        $fedhelmOwned += $fedhelmNext
        $fedhelmFrontier = @($fedhelmNext | ForEach-Object { $_.ProcessId })
    }
    & taskkill /PID $fedhelmInfo.pid /T /F 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $fedhelmAfter = @(Get-CimInstance Win32_Process -Property ProcessId,CreationDate)
        $fedhelmRemaining = @($fedhelmOwned | Where-Object {
            $fedhelmOriginal = $_
            @($fedhelmAfter | Where-Object { $_.ProcessId -eq $fedhelmOriginal.ProcessId -and $_.CreationDate -eq $fedhelmOriginal.CreationDate }).Count -gt 0
        })
        if ($fedhelmRemaining.Count -gt 0) { throw 'Some recorded platform processes remain. Check the original launcher; unrelated processes were not touched.' }
    }
    Write-Host 'Only this recorded FedHELM process tree was stopped. Data files are retained.'
} catch { Write-Host $_; exit 1 }

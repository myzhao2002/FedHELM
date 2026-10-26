$ErrorActionPreference = 'Stop'
try {
    $fedhelmRecord = Join-Path $PSScriptRoot 'runtime\training\launcher.json'
    if (-not (Test-Path -LiteralPath $fedhelmRecord)) { throw 'Launcher record is missing. Use Ctrl+C in the original launcher window.' }
    $fedhelmInfo = Get-Content -LiteralPath $fedhelmRecord -Raw | ConvertFrom-Json
    if ($fedhelmInfo.workspace -ne $PSScriptRoot) { throw 'Workspace mismatch; no process stopped.' }
    $fedhelmProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($fedhelmInfo.pid)"
    if (-not $fedhelmProcess) { Write-Host 'Platform is already stopped.'; exit 0 }
    $fedhelmBirth = ([DateTimeOffset]$fedhelmProcess.CreationDate).ToUnixTimeSeconds()
    if ([Math]::Abs($fedhelmBirth - $fedhelmInfo.recorded_at) -gt 30 -or $fedhelmProcess.CommandLine -notmatch '-m scripts.local') {
        throw 'Process identity mismatch; no process stopped.'
    }
    & taskkill /PID $fedhelmInfo.pid /T /F
    if ($LASTEXITCODE -ne 0) { throw 'Stop failed.' }
    Write-Host 'Only this recorded FedHELM process tree was stopped. Data files are retained.'
} catch { Write-Host $_; exit 1 }

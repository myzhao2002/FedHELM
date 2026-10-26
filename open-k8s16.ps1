$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$null = New-Item -ItemType Directory -Path runtime -Force
$kubectl = (Get-Command kubectl -ErrorAction Stop).Source
foreach ($entry in @(@{Port=16000;Service='edge'},@{Port=16090;Service='injector'})) {
    if (-not (Get-NetTCPConnection -State Listen -LocalPort $entry.Port -ErrorAction SilentlyContinue)) {
        Start-Process -FilePath $kubectl -ArgumentList @('--context','kind-fedhelm16','-n','fedhelm-cluster','port-forward',('svc/'+$entry.Service),($entry.Port.ToString()+':8000')) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $PSScriptRoot ('runtime\forward-'+$entry.Port+'.log')) -RedirectStandardError (Join-Path $PSScriptRoot ('runtime\forward-'+$entry.Port+'-error.log'))
        Write-Host ('Started port forward: '+$entry.Port)
    } else { Write-Host ('Port already listening: '+$entry.Port+'. Existing process was not changed.') }
}
Write-Host 'Console: http://127.0.0.1:16000/lab?ui=nav5'
Write-Host 'Fault lab: http://127.0.0.1:16090/'
Write-Host 'If unavailable, inspect runtime/forward-*-error.log. Re-run after Pod restarts.'

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Checked {
    param([string]$Exe, [string[]]$Arguments)
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed (exit $LASTEXITCODE). Deployment stopped." }
}

try {
    $kind = Join-Path (Get-Location) 'tools\kind.exe'
    if (-not (Test-Path -LiteralPath $kind)) { $kind = (Get-Command kind -ErrorAction Stop).Source }
    $null = Get-Command docker -ErrorAction Stop
    $null = Get-Command kubectl -ErrorAction Stop
    # Fail before changing any cluster when the Linux engine is unavailable.
    $engine = & docker info --format '{{.OSType}}'
    if ($LASTEXITCODE -ne 0 -or "$engine".Trim() -ne 'linux') {
        throw 'Docker Linux Engine is unavailable. Start Docker Desktop (Linux containers), wait for docker info to succeed, then retry.'
    }
    $launcher = 'runtime\cluster\launcher.json'
    if (Test-Path -LiteralPath $launcher) {
        Write-Host 'Stop the project process version with .\stop-cluster.ps1 before running Kubernetes to release memory.'
    }
    Invoke-Checked $kind @('version')
    $env:KIND_EXPERIMENTAL_PROVIDER = 'docker'
    $clusters = & $kind get clusters
    if ($LASTEXITCODE -ne 0) { throw 'Cannot list kind clusters.' }
    if (@($clusters) -notcontains 'fedhelm16') {
        Invoke-Checked $kind @('create', 'cluster', '--name', 'fedhelm16', '--config', 'k8s/kind16.yaml', '--wait', '180s')
    }
    $ctx = @('--context', 'kind-fedhelm16')
    $ns = $ctx + @('-n', 'fedhelm-cluster')
    Invoke-Checked 'kubectl' ($ctx + @('get', 'nodes', '-o', 'wide'))
    Invoke-Checked 'docker' @('build', '-f', 'Dockerfile.training', '-t', 'fedhelm-cluster:k8s16', '.')
    Invoke-Checked $kind @('load', 'docker-image', 'fedhelm-cluster:k8s16', '--name', 'fedhelm16')
    Invoke-Checked 'kubectl' ($ctx + @('apply', '-f', 'k8s/namespace16.json'))
    $auth = & kubectl @ns get secret internal-auth --ignore-not-found -o name
    if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect the internal authentication Secret.' }
    if (-not $auth) {
        $null = New-Item -ItemType Directory -Path 'secrets' -Force
        $tokenFile = Join-Path (Get-Location) 'secrets\k8s-internal.token'
        if (-not (Test-Path -LiteralPath $tokenFile)) {
            $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
            try {
                $bytes = New-Object byte[] 32
                $rng.GetBytes($bytes)
                [System.IO.File]::WriteAllText($tokenFile, [Convert]::ToBase64String($bytes), (New-Object System.Text.UTF8Encoding($false)))
            } finally { $rng.Dispose() }
        }
        Invoke-Checked 'kubectl' ($ns + @('create', 'secret', 'generic', 'internal-auth', "--from-file=token=$tokenFile"))
    }
    Invoke-Checked 'kubectl' ($ctx + @('apply', '-f', 'k8s/cluster16-local.json'))
    # Also refresh existing Pods after loading a rebuilt local image with the same tag.
    Invoke-Checked 'kubectl' ($ns + @('rollout', 'restart', 'deployment'))
    Invoke-Checked 'kubectl' ($ns + @('wait', '--for=condition=Available', 'deployment', '--all', '--timeout=600s'))
    Invoke-Checked 'kubectl' ($ns + @('get', 'pods,pvc,svc', '-o', 'wide'))
    Write-Host 'Kubernetes deployments are Available. Verify the counts and business workflow using the tutorial.'
    Write-Host 'Keep TWO PowerShell windows open with these commands:'
    Write-Host 'kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/edge 16000:8000'
    Write-Host 'kubectl --context kind-fedhelm16 -n fedhelm-cluster port-forward svc/injector 16090:8000'
} catch {
    Write-Host ('STOPPED: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}

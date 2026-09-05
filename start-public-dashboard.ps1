$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$localDir = Join-Path $PSScriptRoot '.local'
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$tunnel = Join-Path $localDir 'cloudflared.exe'
if (-not (Test-Path -LiteralPath $tunnel)) {
    throw 'Download cloudflared-windows-amd64.exe from the official Cloudflare GitHub releases to .local/cloudflared.exe first.'
}
if (Test-Path -LiteralPath (Join-Path $localDir 'public-processes.json')) {
    throw 'A previous public session is recorded. Run stop-public-dashboard.ps1 first.'
}
$bytes = New-Object byte[] 24
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$rng.Dispose()
$env:PUBLIC_DASHBOARD_PASSWORD = [Convert]::ToBase64String($bytes)
$env:ENABLE_AI_ADVISOR = 'false'
$dashboardProcess = $null
try {
    $dashboardProcess = Start-Process -FilePath $python -ArgumentList '-m streamlit run public_dashboard.py --server.address 127.0.0.1 --server.port 8502 --server.headless true' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $localDir 'public-dashboard.log') -RedirectStandardError (Join-Path $localDir 'public-dashboard-error.log')
    $ready = $false
    for ($i = 0; $i -lt 30; $i++) {
        Start-Sleep -Seconds 1
        $dashboardProcess.Refresh()
        if ($dashboardProcess.HasExited) { throw 'Public dashboard exited. Check .local/public-dashboard-error.log.' }
        try {
            $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8502/_stcore/health' -TimeoutSec 2
            if ($response.StatusCode -eq 200) { $ready = $true; break }
        } catch { }
    }
    if (-not $ready) { throw 'Public dashboard did not become ready.' }
    $tunnelProcess = Start-Process -FilePath $tunnel -ArgumentList 'tunnel --url http://127.0.0.1:8502 --no-autoupdate' -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $localDir 'tunnel.log') -RedirectStandardError (Join-Path $localDir 'tunnel-error.log')
    @(@{ Id = $dashboardProcess.Id; StartTime = $dashboardProcess.StartTime.ToUniversalTime().ToString('o') }, @{ Id = $tunnelProcess.Id; StartTime = $tunnelProcess.StartTime.ToUniversalTime().ToString('o') }) | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $localDir 'public-processes.json')
    Set-Content -LiteralPath (Join-Path $localDir 'public-password.txt') -Value $env:PUBLIC_DASHBOARD_PASSWORD
    Write-Output 'Started. Password: .local/public-password.txt. Temporary URL: .local/tunnel-error.log.'
} catch {
    if ($dashboardProcess -and -not $dashboardProcess.HasExited) { Stop-Process -Id $dashboardProcess.Id }
    throw
} finally {
    Remove-Item Env:PUBLIC_DASHBOARD_PASSWORD -ErrorAction SilentlyContinue
}

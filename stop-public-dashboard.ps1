$ErrorActionPreference = 'Stop'
$record = Join-Path $PSScriptRoot '.local/public-processes.json'
if (Test-Path -LiteralPath $record) {
    foreach ($entry in (Get-Content -LiteralPath $record -Raw | ConvertFrom-Json)) {
        $process = Get-Process -Id $entry.Id -ErrorAction SilentlyContinue
        if ($process -and $process.StartTime.ToUniversalTime().ToString('o') -eq $entry.StartTime) {
            Stop-Process -Id $process.Id
        }
    }
    Remove-Item -LiteralPath $record
}
Write-Output 'Public dashboard and tunnel stopped. The trading bot and Wi-Fi dashboard are unaffected.'

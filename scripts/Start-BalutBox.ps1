#requires -Version 7.2
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
& (Join-Path $PSScriptRoot 'Start-BoxCamera.ps1')
$taskProfilePath = Join-Path $taskRoot 'deployment\private\windows-phone.json'
$taskProfile = Get-Content -LiteralPath $taskProfilePath -Raw | ConvertFrom-Json
$taskExisting = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains('balut_api.service_runner') -and $_.CommandLine.Contains($taskProfilePath)
}
if (-not $taskExisting) {
    $taskPowerShell = (Get-Process -Id $PID).Path
    $taskLauncher = Join-Path $PSScriptRoot 'Start-Balut.ps1'
    Start-Process -FilePath $taskPowerShell -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "' + $taskLauncher + '" -Phone -Supervise') `
        -WorkingDirectory $taskRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $taskRoot 'deployment\logs\box-service.out.log') `
        -RedirectStandardError (Join-Path $taskRoot 'deployment\logs\box-service.err.log') | Out-Null
}
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    try {
        $taskReady = Invoke-RestMethod -Uri ($taskProfile.https_origin + '/ready') -TimeoutSec 2
        if ($taskReady.serviceReady) { Write-Output ('Balut is ready: ' + $taskProfile.https_origin); return }
    } catch { }
    Start-Sleep -Seconds 1
}
throw 'The web service did not become ready. Inspect deployment/logs/service.log.'

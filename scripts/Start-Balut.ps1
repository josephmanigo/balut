param([switch]$Supervise, [switch]$Phone)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskPython = Join-Path $taskRoot '.venv-serving\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = Join-Path $taskRoot 'runtime\python\python.exe' }
$taskProfile = Join-Path $taskRoot 'deployment\private\windows.json'
if ($Phone) { $taskProfile = Join-Path $taskRoot 'deployment\private\windows-phone.json' }
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Extract the complete school kit, or install the .venv-serving environment first.' }
if (-not (Test-Path -LiteralPath $taskProfile)) { throw 'Run Initialize-Serving.ps1 first.' }
$taskExisting = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -like '*balut_api.service_runner*' -and
    ($_.CommandLine.Contains((Join-Path $taskRoot 'deployment\private\windows.json')) -or
     $_.CommandLine.Contains((Join-Path $taskRoot 'deployment\private\windows-phone.json')))
}
if ($taskExisting) { throw 'Balut is already running. Stop that service before switching between PC and phone mode.' }
$taskOldPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $taskRoot 'apps\edge_api'
    $taskAttempt = 0
    do {
        & $taskPython -m balut_api.service_runner --profile $taskProfile
        $taskExitCode = $LASTEXITCODE
        if ($taskExitCode -eq 0) { break }
        $taskAttempt++
        if (-not $Supervise -or $taskAttempt -ge 5) { throw "Service failed with exit code $taskExitCode; inspect deployment/logs/service.log." }
        Write-Warning 'Service exited unexpectedly; retrying. Model and configuration checks still run at startup.'
        Start-Sleep -Seconds ([Math]::Min(30, [Math]::Pow(2, $taskAttempt)))
    } while ($Supervise)
}
finally { $env:PYTHONPATH = $taskOldPath }

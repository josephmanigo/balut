$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskScript = Join-Path $PSScriptRoot 'camera_usb_bridge.py'
$taskPython = Join-Path $taskRoot '.venv-hardware\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'The camera Python environment is missing.' }
$taskExisting = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object {
    $_.CommandLine -and $_.CommandLine.Contains($taskScript)
}
if (-not $taskExisting) {
    New-Item -ItemType Directory -Path (Join-Path $taskRoot 'deployment\logs') -Force | Out-Null
    Start-Process -FilePath $taskPython -ArgumentList ('"' + $taskScript + '"') -WorkingDirectory $taskRoot -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $taskRoot 'deployment\logs\camera-usb.out.log') `
        -RedirectStandardError (Join-Path $taskRoot 'deployment\logs\camera-usb.err.log') | Out-Null
}
for ($taskAttempt = 0; $taskAttempt -lt 15; $taskAttempt++) {
    $taskListener = Get-NetTCPConnection -State Listen -LocalPort 8767 -ErrorAction SilentlyContinue
    if ($taskListener) {
        $taskOwner = Get-CimInstance Win32_Process -Filter "ProcessId = $($taskListener.OwningProcess)"
        if (-not $taskOwner.CommandLine -or -not $taskOwner.CommandLine.Contains($taskScript)) { throw 'Camera port 8767 is occupied by another program.' }
        New-Item -ItemType Directory -Path (Join-Path $taskRoot 'deployment\runtime') -Force | Out-Null
        $taskOwner.ProcessId | Set-Content -LiteralPath (Join-Path $taskRoot 'deployment\runtime\camera-usb.pid')
        Write-Output 'USB camera bridge is running.'
        return
    }
    Start-Sleep -Seconds 1
}
throw 'The USB camera bridge did not start. Check the camera cable and deployment/logs/camera-usb.err.log.'
